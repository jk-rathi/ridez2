"""End-to-end encrypted JSON between the browser and the API.

Hides user data from the browser's Network tab and from anything that can read traffic
before TLS (proxies, extensions, logs). It is not a substitute for HTTPS.

Handshake (POST /api/v1/secure/handshake, plaintext, carries no user data):
  browser -> {client_public_key}           ephemeral P-256 public key, raw, base64
  server  -> {server_public_key, salt, channel, expires_at}
Both sides compute ECDH(P-256) -> HKDF-SHA256(salt, info="ridez-api-v1") -> AES-256-GCM key.
The key itself is never sent. ``channel`` is that key sealed with a server-only key
(derived from JWT_SECRET), so the server stays stateless across workers and restarts.

Every later request sends ``X-Ridez-Channel: <channel>``. Its JSON body, and the JSON
response, are then envelopes: {"enc": "v1", "iv": base64(12 bytes), "data": base64(ciphertext)}.
Requests without the header keep working in plaintext (tests, curl, health checks).
"""
import base64
import binascii
import json
import os
import time
from flask import Request, current_app, g, jsonify, request
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from .routes import api, body
from .services import ApiError

HEADER = 'X-Ridez-Channel'
VERSION = 'v1'
INFO = b'ridez-api-v1'
REQUEST_AAD = b'ridez-api-v1:request'
RESPONSE_AAD = b'ridez-api-v1:response'
CHANNEL_SECONDS = 12 * 60 * 60
_MISSING = object()


def b64(data):
    return base64.b64encode(data).decode()


def unb64(value, label, urlsafe=False):
    if not isinstance(value, str):
        raise ApiError(f'{label} is invalid')
    try:
        return (base64.urlsafe_b64decode if urlsafe else base64.b64decode)(value.encode() + b'=' * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raise ApiError(f'{label} is invalid')


def hkdf(material, info, salt=None):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(material)


def _sealer():
    secret = current_app.config['JWT_SECRET'].encode()
    return AESGCM(hkdf(secret, b'ridez-api-channel-token-v1'))


def issue(client_public_key):
    """Run the server half of the key exchange. Returns the handshake response."""
    try:
        client = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(client_public_key, 'Client public key'))
    except ValueError:
        raise ApiError('Client public key is invalid')
    server = ec.generate_private_key(ec.SECP256R1())
    salt = os.urandom(16)
    key = hkdf(server.exchange(ec.ECDH(), client), INFO, salt)
    expires = int(time.time()) + CHANNEL_SECONDS
    nonce = os.urandom(12)
    sealed = nonce + _sealer().encrypt(nonce, json.dumps({'k': b64(key), 'exp': expires}).encode(), b'channel')
    public = server.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return dict(server_public_key=b64(public), salt=b64(salt), channel=base64.urlsafe_b64encode(sealed).decode().rstrip('='), expires_at=expires)


def open_channel(token):
    """Return the AES key sealed in a channel token, or None if it is invalid or expired."""
    try:
        raw = unb64(token, 'Channel', urlsafe=True)
        if len(raw) < 13:
            return None
        claims = json.loads(_sealer().decrypt(raw[:12], raw[12:], b'channel'))
        if claims['exp'] <= time.time():
            return None
        return base64.b64decode(claims['k'])
    except (ApiError, InvalidTag, ValueError, KeyError, TypeError):
        return None


def seal(key, payload, aad):
    nonce = os.urandom(12)
    return {'enc': VERSION, 'iv': b64(nonce), 'data': b64(AESGCM(key).encrypt(nonce, payload, aad))}


def unseal(key, envelope, aad):
    if not isinstance(envelope, dict) or envelope.get('enc') != VERSION:
        raise ApiError('This connection is encrypted. Send an encrypted request body')
    nonce = unb64(envelope.get('iv'), 'Encrypted request')
    if len(nonce) != 12:
        raise ApiError('Encrypted request is invalid')
    try:
        return AESGCM(key).decrypt(nonce, unb64(envelope.get('data'), 'Encrypted request'), aad)
    except InvalidTag:
        raise ApiError('Encrypted request could not be verified')


class SecureRequest(Request):
    """Serves the decrypted body to get_json()/request.json, so routes need no changes."""

    def get_json(self, force=False, silent=False, cache=True):
        decrypted = self.__dict__.get('_ridez_json', _MISSING)
        if decrypted is not _MISSING:
            return decrypted
        return super().get_json(force=force, silent=silent, cache=cache)


@api.post('/secure/handshake')
def handshake():
    return jsonify(issue(body().get('client_public_key')))


@api.before_request
def decrypt_request():
    token = request.headers.get(HEADER)
    if not token:
        return None
    key = open_channel(token)
    if key is None:
        response = jsonify(error='Your secure connection expired. Please retry')
        response.status_code = 400
        response.headers[HEADER] = 'renew'
        return response
    g.channel_key = key
    current = request._get_current_object()
    if current.get_data(cache=True):
        envelope = Request.get_json(current, silent=True)
        plaintext = unseal(key, envelope, REQUEST_AAD)
        try:
            current.__dict__['_ridez_json'] = json.loads(plaintext)
        except ValueError:
            raise ApiError('Encrypted request is not valid JSON')
    return None


@api.after_request
def encrypt_response(response):
    key = g.pop('channel_key', None)
    if key is None or response.mimetype != 'application/json' or response.direct_passthrough:
        return response
    response.set_data(json.dumps(seal(key, response.get_data(), RESPONSE_AAD)))
    response.headers['X-Ridez-Encrypted'] = VERSION
    return response

import base64
import json
import os
from unittest.mock import patch
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from test_auth import app, client, signup


class Browser:
    """Does exactly what frontend/src/secureChannel.js does, to test the server half."""

    def __init__(self, client):
        self.client = client
        private = ec.generate_private_key(ec.SECP256R1())
        public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        response = client.post('/api/v1/secure/handshake', json={'client_public_key': base64.b64encode(public).decode()})
        assert response.status_code == 200, response.json
        self.handshake = response.json
        server = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(response.json['server_public_key']))
        shared = private.exchange(ec.ECDH(), server)
        self.key = HKDF(hashes.SHA256(), 32, base64.b64decode(response.json['salt']), b'ridez-api-v1').derive(shared)
        self.token = response.json['channel']

    def seal(self, payload):
        iv = os.urandom(12)
        data = AESGCM(self.key).encrypt(iv, json.dumps(payload).encode(), b'ridez-api-v1:request')
        return {'enc': 'v1', 'iv': base64.b64encode(iv).decode(), 'data': base64.b64encode(data).decode()}

    def unseal(self, envelope):
        assert set(envelope) == {'enc', 'iv', 'data'}
        plain = AESGCM(self.key).decrypt(base64.b64decode(envelope['iv']), base64.b64decode(envelope['data']), b'ridez-api-v1:response')
        return json.loads(plain)

    def request(self, method, path, payload=None, headers=None):
        kwargs = {'headers': {'X-Ridez-Channel': self.token, **(headers or {})}}
        if payload is not None:
            kwargs['json'] = self.seal(payload)
        return getattr(self.client, method)(f'/api/v1{path}', **kwargs)


def test_handshake_exposes_no_key_material(client):
    browser = Browser(client)
    assert set(browser.handshake) == {'server_public_key', 'salt', 'channel', 'expires_at'}
    assert base64.b64encode(browser.key).decode() not in json.dumps(browser.handshake)
    assert len(base64.b64decode(browser.handshake['server_public_key'])) == 65


def test_login_and_profile_are_encrypted_both_ways(client):
    assert signup(client).status_code == 201
    browser = Browser(client)
    login = browser.request('post', '/auth/login', {'mobile': '+919876543210', 'password': 'correct-horse-battery'})
    assert login.status_code == 200 and login.headers['X-Ridez-Encrypted'] == 'v1'
    raw = login.get_data(as_text=True)
    assert 'Asha' not in raw and '9876543210' not in raw and 'access_token' not in raw
    session = browser.unseal(login.json)
    assert session['user']['name'] == 'Asha'
    me = browser.request('get', '/me', headers={'Authorization': f"Bearer {session['access_token']}"})
    assert 'Asha' not in me.get_data(as_text=True)
    assert browser.unseal(me.json)['user']['mobile'] == '+919876543210'


def test_errors_are_encrypted_too(client):
    browser = Browser(client)
    failed = browser.request('post', '/auth/login', {'mobile': '+919876543210', 'password': 'wrong-password-123'})
    assert failed.status_code == 401
    assert 'error' not in failed.json and 'error' in browser.unseal(failed.json)


def test_plaintext_body_is_rejected_on_an_encrypted_channel(client):
    browser = Browser(client)
    response = client.post('/api/v1/auth/login', json={'mobile': '+919876543210', 'password': 'x'}, headers={'X-Ridez-Channel': browser.token})
    assert response.status_code == 400
    assert 'encrypted' in browser.unseal(response.json)['error']


def test_tampered_body_is_rejected(client):
    browser = Browser(client)
    envelope = browser.seal({'mobile': '+919876543210', 'password': 'correct-horse-battery'})
    data = bytearray(base64.b64decode(envelope['data']))
    data[0] ^= 1
    envelope['data'] = base64.b64encode(bytes(data)).decode()
    response = client.post('/api/v1/auth/login', json=envelope, headers={'X-Ridez-Channel': browser.token})
    assert response.status_code == 400 and 'verified' in browser.unseal(response.json)['error']


def test_invalid_or_expired_channel_asks_browser_to_renew(client):
    for token in ['not-a-channel', Browser(client).token[:-4] + 'AAAA']:
        response = client.get('/api/v1/health', headers={'X-Ridez-Channel': token})
        assert response.status_code == 400 and response.headers['X-Ridez-Channel'] == 'renew'
    browser = Browser(client)
    with patch('app.secure_channel.time.time', return_value=browser.handshake['expires_at'] + 1):
        response = browser.request('get', '/health')
    assert response.headers['X-Ridez-Channel'] == 'renew'


def test_channel_from_another_server_secret_is_rejected(app, client):
    browser = Browser(client)
    app.config['JWT_SECRET'] = 'a-different-secret-for-another-server-1234'
    assert browser.request('get', '/health').headers['X-Ridez-Channel'] == 'renew'


def test_bad_public_key_is_rejected(client):
    for value in ['', 'AAAA', base64.b64encode(b'\x04' + b'\x00' * 64).decode(), 123]:
        assert client.post('/api/v1/secure/handshake', json={'client_public_key': value}).status_code == 400


def test_plaintext_clients_still_work(client):
    assert signup(client).status_code == 201
    assert client.post('/api/v1/auth/login', json={'mobile': '+919876543210', 'password': 'correct-horse-battery'}).json['user']['name'] == 'Asha'

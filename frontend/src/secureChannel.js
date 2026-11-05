// Encrypted JSON between the browser and the API; see backend/app/secure_channel.py.
// The Network tab only shows {enc, iv, data} envelopes. The AES key is derived with ECDH and
// kept as a non-extractable CryptoKey, so it never travels over the network and page scripts
// cannot export it.
const VERSION = 'v1';
const encoder = new TextEncoder(), decoder = new TextDecoder();
const REQUEST_AAD = encoder.encode('ridez-api-v1:request');
const RESPONSE_AAD = encoder.encode('ridez-api-v1:response');
let channel = null, pending = null, warned = false;

function toBase64(bytes) {
  const view = new Uint8Array(bytes);
  let text = '';
  for (let i = 0; i < view.length; i += 0x8000) text += String.fromCharCode(...view.subarray(i, i + 0x8000));
  return btoa(text);
}
const fromBase64 = value => Uint8Array.from(atob(value), char => char.charCodeAt(0));

// Web Crypto only exists on HTTPS and localhost. Plain-HTTP LAN addresses fall back to plaintext.
export const encryptionAvailable = () => Boolean(globalThis.isSecureContext && globalThis.crypto?.subtle);

async function handshake() {
  const pair = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  const publicKey = await crypto.subtle.exportKey('raw', pair.publicKey);
  const response = await fetch('/api/v1/secure/handshake', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_public_key: toBase64(publicKey) }) });
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok || !data.channel) throw new Error(data.error || 'Unable to start a secure connection. Please retry.');
  const server = await crypto.subtle.importKey('raw', fromBase64(data.server_public_key), { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = await crypto.subtle.deriveBits({ name: 'ECDH', public: server }, pair.privateKey, 256);
  const material = await crypto.subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt: fromBase64(data.salt), info: encoder.encode('ridez-api-v1') }, material, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  // Renew a minute early so a request never races the server-side expiry.
  return { key, token: data.channel, renewAt: (data.expires_at - 60) * 1000 };
}

function currentChannel() {
  if (channel && Date.now() < channel.renewAt) return Promise.resolve(channel);
  if (!pending) pending = handshake().then(value => (channel = value)).finally(() => { pending = null; });
  return pending;
}

async function seal(key, text) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: REQUEST_AAD }, key, encoder.encode(text));
  return JSON.stringify({ enc: VERSION, iv: toBase64(iv), data: toBase64(data) });
}

async function unseal(key, envelope) {
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromBase64(envelope.iv), additionalData: RESPONSE_AAD }, key, fromBase64(envelope.data));
  return JSON.parse(decoder.decode(plain));
}

async function readJson(response) {
  try { return await response.json(); } catch { return undefined; }
}

// fetch() for the JSON API. Returns {response, data}; data is the decrypted JSON body, or
// undefined when the body was not JSON. The request body must be a JSON string or absent.
export async function secureFetch(url, options = {}, retry = true) {
  if (!encryptionAvailable()) {
    if (!warned) { warned = true; console.warn('ridez: this page is not on HTTPS or localhost, so API traffic is not end-to-end encrypted.'); }
    const response = await fetch(url, options);
    return { response, data: await readJson(response) };
  }
  const active = await currentChannel();
  const body = options.body == null ? options.body : await seal(active.key, options.body);
  const response = await fetch(url, { ...options, body, headers: { ...options.headers, 'X-Ridez-Channel': active.token } });
  if (response.headers.get('X-Ridez-Channel') === 'renew') {
    if (channel === active) channel = null;
    if (retry) return secureFetch(url, options, false);
  }
  const data = await readJson(response);
  if (data?.enc !== VERSION) return { response, data };
  try {
    return { response, data: await unseal(active.key, data) };
  } catch {
    if (channel === active) channel = null;
    throw new Error('Unable to read the secure server response. Please retry.');
  }
}

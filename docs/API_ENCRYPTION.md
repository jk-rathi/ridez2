# Encrypted API traffic

Every JSON request and response between the website and the API is encrypted, so the browser's
**Inspect → Network** tab shows only envelopes like this, never names, mobile numbers, fares,
passwords or tokens:

```json
{"enc": "v1", "iv": "Q7bHEenPWKGgPj9w", "data": "5I/IoF2higEFBQ2M…"}
```

## How it works

1. When the page loads, the browser creates a temporary P-256 key pair and sends only its
   **public** key to `POST /api/v1/secure/handshake`. The server replies with its own public key,
   a random salt and an opaque `channel` token. This exchange contains no user data.
2. Both sides compute the same AES-256-GCM key with ECDH + HKDF-SHA256. **The key is never sent
   over the network.** In the browser it is a non-extractable Web Crypto key, so page scripts
   can use it but cannot read or export it.
3. Every API call then sends `X-Ridez-Channel: <channel>`. The request body and the JSON
   response, including error messages, are encrypted and authenticated. A tampered message is
   rejected.
4. The channel token is the key sealed with a server-only key derived from `JWT_SECRET`, so any
   server worker can read it and no server-side storage is needed. Channels last 12 hours. The
   browser renews them automatically, and if the server answers `X-Ridez-Channel: renew` it
   re-handshakes and retries once.

Code: `backend/app/secure_channel.py` (server) and `frontend/src/secureChannel.js` (browser).
Tests: `backend/tests/test_secure_channel.py`.

## What it does and doesn't protect

- **Protected:** the Network tab, HAR exports, browser extensions and proxies that read
  traffic, and request/response logging anywhere between the page and Flask.
- **Not hidden from the person using the page:** the screen has to show the user their own data,
  so it still appears in the Elements tab, in React DevTools and in the JavaScript debugger.
  No website can hide data from its own user's browser.
- **Still visible in the Network tab:** URLs (which can include ride IDs), the
  `Authorization` header, cookies, and Socket.IO messages. Socket.IO only carries
  "something changed" notifications (an event ID and a timestamp), never user data.
- **Not a replacement for HTTPS.** Production must still use HTTPS. It also protects the
  handshake and cookies.

## Plain-HTTP fallback

Browsers only provide Web Crypto on **HTTPS** and **localhost**. If you open the dev server through
a plain-HTTP LAN address (for example `http://192.168.1.20:5173` on a phone), the page still works
but sends plaintext, and logs a warning in the browser console. Use localhost or an HTTPS tunnel
when you need encrypted traffic on another device.

## Other clients

Requests without the `X-Ridez-Channel` header still use plain JSON, so `curl`, the test suite,
health checks and deployment smoke tests keep working unchanged. A request that sends the header
must encrypt its body. Plain JSON is rejected on an encrypted channel.

## Debugging

To read a decrypted response during development, use React DevTools (component state) or log
`data` inside `frontend/src/api.js`. Remove that log before committing.

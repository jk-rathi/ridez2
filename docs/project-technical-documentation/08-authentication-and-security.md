# 08 — Authentication, authorization and security

[← Back to index](README.md) · Next: [09 — Feature-by-feature explanation →](09-feature-by-feature-explanation.md) · Sequences: [diagrams/sequences-auth.md](diagrams/sequences-auth.md)

## 1. Summary

| Concern | Implementation | Status |
| --- | --- | --- |
| Identity | Mobile number (E.164) + password | Implemented; **mobile ownership is not verified** (no SMS) |
| Password storage | Werkzeug `generate_password_hash` (default algorithm of Werkzeug 3.x, which is scrypt **(inferred from library version)**) | Implemented |
| Access token | JWT HS256, 15 min, claims `sub, sid, iat, exp`, held in browser memory | Implemented |
| Refresh | Opaque 48-byte random token in HttpOnly cookie, SHA-256 hashed in DB, single-use rotation, replay → revoke session, 30-day absolute session | Implemented |
| Revocation | Every request validates the DB session row | Implemented |
| RBAC | `@authenticated(role)` + per-resource ownership checks | Implemented |
| CSRF | Bearer tokens for business APIs; custom header + Origin + Sec-Fetch-Site checks on cookie endpoints | Implemented |
| CORS | None configured — same-origin deployment | By design |
| Rate limiting | In-memory, per-process: auth 10/min/IP, quotes 10/min/rider, OTP 5 failures/min/driver | **Partial** (not shared, resets on restart) |
| Input validation | Hand-written per field in services | Implemented |
| Security headers | nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, HSTS on HTTPS | Implemented; **no CSP** |
| Secrets | Env vars; prod requires ≥ 32 chars and distinct; dev auto-generates to `instance/` | Implemented |
| Account recovery / password reset / MFA | — | **Not implemented** |
| Account disabling | `disabled` status honoured everywhere | Honoured, but **no endpoint sets it** |

## 2. Registration

`POST /api/v1/auth/register` → `routes.registration` → `services.register(data)`:

1. `limit_auth` before_request allows 10 POSTs per minute per client IP across login/register.
2. `body()` requires a JSON object.
3. Validates name (1–100 after trim), password (10–128 chars; no complexity rules), role (`rider`/`driver`; `admin` only when `allow_admin=True`, i.e. CLI/bootstrap).
4. `normalize(mobile)`: `phonenumbers.parse(value, None)` requires an international prefix, `is_valid_number`, returns E.164.
5. Duplicate check → 409; unique constraint is the final guard (IntegrityError → 409).
6. Permanent `user_code` from HMAC (see [05 §3](05-backend-documentation.md#3-accounts-servicespy)). Codes are identifiers, **not** credentials.
7. Drivers start `pending`; riders `active`.

## 3. Login

`POST /api/v1/auth/login` → `check_origin(require_header=False)` → `services.login` → `session_service.issue`:

1. Malformed mobile, non-string or > 128-char password, unknown user, wrong password, disabled user → identical `401 Mobile or password is incorrect`.
2. For unknown users the password is still checked against a cached dummy hash (`DUMMY_HASH`), equalizing timing.
3. `issue(user)` creates `auth_sessions` (expires in `REFRESH_SESSION_DAYS`, 30) and a refresh token; commits.
4. Response: `{access_token, expires_in, expires_at, user}` + `Set-Cookie ridez_refresh`.

Login doesn't require `X-Session-Request` (so a plain form could post) but does reject a foreign `Origin` and `Sec-Fetch-Site: cross-site` — this blocks **login CSRF** (an attacker logging the victim into the attacker's account).

## 4. Tokens

### Access token (JWT)

```python
expires = min(issued + timedelta(minutes=15), session.expires_at)
jwt.encode({'sub': str(user.id), 'sid': session.id, 'iat': issued, 'exp': expires}, JWT_SECRET, algorithm='HS256')
```

- Verified by `session_service.authenticate` with `algorithms=['HS256']` (prevents algorithm confusion) and `options={'require': ['sub','sid','iat','exp']}`.
- Because `sid` must reference a valid, unrevoked, unexpired session owned by `sub`, a stolen JWT stops working immediately after logout.
- Stored only in a JS module variable; never in `localStorage`/`sessionStorage` — not readable after a reload, which is why the SPA refreshes on boot.

### Refresh token (cookie)

| Attribute | Value | Reason |
| --- | --- | --- |
| Name | `ridez_refresh` | |
| Value | `secrets.token_urlsafe(48)` | ~384 bits of entropy |
| Storage | `refresh_tokens.token_hash = sha256(value)` | DB leak doesn't expose usable tokens |
| `HttpOnly` | yes | XSS cannot read it |
| `Secure` | `AUTH_COOKIE_SECURE` (= not development) | HTTPS only in prod |
| `SameSite` | `Lax` | Not sent on cross-site POSTs |
| `Path` | `/api/v1/auth` | Not sent to any other endpoint |
| `Max-Age` | 30 days | |

**Rotation:** each refresh marks the presented token used (conditional UPDATE) and issues a new one in the same session. **Replay detection:** presenting an already-used token revokes the whole session (both attacker and victim are signed out). **Expiry:** the session's absolute expiry is not extended; after 30 days the user must log in again.

## 5. How a request is authenticated and authorized (exact path)

1. Browser `api()` sends `Authorization: Bearer <token>`.
2. `routes.authenticated(role)` rejects missing/malformed headers → 401.
3. `session_service.authenticate(token)`:
   - `jwt.decode` (signature, `exp`, required claims) → `jwt.InvalidTokenError` → 401.
   - `User` by `sub`; missing or `disabled` → 401.
   - `valid_session(sid, user.id)` → None → 401.
4. Role gate: `role` argument vs `g.user.role` → 403.
5. Service-level authorization, e.g.:
   - `ride_service.accessible`: participant or admin, else 404.
   - `move`: transitions only by `ride.driver_id`; cancel by rider or assigned driver.
   - `payment_service.choose`: `ride.rider_id == user.id`; `confirm_cash`: `ride.driver_id == user.id`.
   - `rating_service.submit`: participant of the ride.
   - `trip_map`: rider/driver participant only (admins excluded to protect live location).
   - `location_service.update`: only the authenticated driver's own row (`user.id`).
6. Data-level privacy in serializers: riders never get `settlement`; invitations never include settlement; `location_service.public` omits coordinates; `ratings` with comments only for admins; `trip_otp` only in the rider's own snapshot.

### Role matrix

| Capability | Rider | Driver | Admin |
| --- | --- | --- | --- |
| Quote / book | ✓ | | |
| Cancel | own ride (pre-start) | assigned ride (ASSIGNED..WAITING) | ✗ |
| Availability / location / accept / reject / progress | | ✓ (active) | |
| Choose payment method / test QR | ✓ | | |
| Confirm cash | | ✓ | |
| Rate | ✓ | ✓ | ✗ |
| View ride | participant | participant | any |
| Trip map | participant | participant | ✗ |
| Admin endpoints | | | ✓ |
| `/workspace` | own | own | all rides (100), metrics, drivers |

## 6. Logout

- `POST /auth/logout`: session found via cookie, else Bearer `sid`; `revoke()` sets `revoked_at` and calls `stop_requests`; cookie deleted; `realtime.disconnect_invalid()` closes the session's sockets.
- `POST /auth/logout-all`: requires a valid Bearer; revokes **all** sessions of the user.
- Frontend broadcasts `signed-out` to other tabs (`BroadcastChannel`).
- Logout **does not** cancel an active trip (tested in `test_sessions.py::test_driver_logout_stops_matching_and_preserves_active_ride`).

## 7. CSRF and origin defence (`session_service.check_origin`)

```python
if require_header and request.headers.get('X-Session-Request') != '1': 403
origin = request.headers.get('Origin')
allowed = {request.host_url.rstrip('/'), *AUTH_TRUSTED_ORIGINS}
if origin and origin not in allowed: 403
if request.headers.get('Sec-Fetch-Site') == 'cross-site': 403
```

- A custom header cannot be added by a cross-site HTML form, and a cross-site `fetch` with a custom header would need a CORS preflight that the server never approves.
- `TRUST_PROXY_HEADERS=1` + `ProxyFix(x_proto=1)` makes `request.host_url` `https://…` behind Render so the Origin comparison works.
- Business endpoints use Bearer tokens (not cookies), so they are not CSRF-able.

## 8. Rate limiting

| Limiter | Key | Limit | Storage | File |
| --- | --- | --- | --- | --- |
| Auth | `request.remote_addr` | 10 POSTs to `/auth/login` + `/auth/register` per 60 s | `app.extensions['auth_attempts']` | `routes.limit_auth` |
| Quotes | rider id | 10 per 60 s | `extensions['quote_attempts']` | `ride_routes.quote` |
| Trip OTP | driver id | 5 **failed** attempts per 60 s | `extensions['trip_otp_attempts']` | `services.verify_trip_otp` |

All are sliding windows using `collections.deque` and `time.monotonic()`. They are **process-local** (comment in code: "Development limiter only; deploy a shared Redis limiter before multiple workers") and reset on restart. Behind a proxy without `TRUST_PROXY_HEADERS=1`, every client shares the proxy's IP and therefore one auth bucket. There is no per-account lockout.

## 9. Trip OTP

`trip_otp(ride) = HMAC_SHA256(USER_CODE_SECRET, "trip-otp:v2:" + ride.id) mod 10^6`, zero-padded.

- Different for every ride; stable across restarts (no DB column needed).
- Shown only to the rider (`snapshot.trip_otp`) while the ride is SEARCHING/ASSIGNED/ARRIVING/WAITING.
- Verified with `hmac.compare_digest`; 5 failures/min/driver.
- It is a reusable pickup PIN, **not** an SMS one-time code. Rotating `USER_CODE_SECRET` changes OTPs for unstarted rides.

## 10. Mock payment capability URLs

`/test-payment/<token>` uses `itsdangerous.URLSafeTimedSerializer(JWT_SECRET, salt='mock-qr-payment-v1')`, `max_age=900`. Anyone holding the URL can change that ride's **mock** status for 15 minutes without logging in; it exposes only amount, currency and status. `Referrer-Policy: no-referrer` on that page prevents the token leaking through the Referer header. The whole feature is disabled unless `TEST_PAYMENTS_ENABLED=1` (default off outside development).

## 11. Input validation and sanitization

- No schema library; each service validates types explicitly (e.g. rejects `bool` where numbers are expected, because `True` is an `int` in Python).
- Strings are trimmed and length-bounded; numbers are bounded and must be finite.
- SQL injection: all queries use SQLAlchemy parameter binding. User search terms are additionally escaped for `ILIKE` wildcards (`\`, `%`, `_`).
- Output encoding: React escapes text by default; there is no `dangerouslySetInnerHTML` in the codebase. The only raw HTML is the static Swagger page string in `routes.docs`.
- Google error responses are filtered (`denial_reason`) so vendor text is never echoed to users.
- Logging: Gunicorn access log is disabled (URLs contain Socket.IO session IDs); the worker logs a generic message without exception payloads (to avoid leaking coordinates).

## 12. Security headers (`web.py::security_headers`, app-wide)

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` on `/test-payment/*`, otherwise `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(self)` |
| `X-Frame-Options` | `DENY` (clickjacking) |
| `Strict-Transport-Security` | `max-age=31536000` when the request is HTTPS |
| `Cache-Control` | `no-store` on all API responses |

Missing: `Content-Security-Policy`.

## 13. Security-related environment variables (names only)

`APP_ENV`, `JWT_SECRET`, `USER_CODE_SECRET`, `AUTH_TRUSTED_ORIGINS`, `TRUST_PROXY_HEADERS`, `TEST_PAYMENTS_ENABLED`, `GOOGLE_MAPS_SERVER_KEY`, `VITE_GOOGLE_MAPS_BROWSER_KEY` (public by design, must be referrer-restricted), `BOOTSTRAP_ADMIN`, `BOOTSTRAP_ADMIN_MOBILE`, `BOOTSTRAP_ADMIN_NAME`, `BOOTSTRAP_ADMIN_PASSWORD` (unset before Gunicorn starts), `DATABASE_URL`.

Production boot fails if `JWT_SECRET`/`USER_CODE_SECRET` are missing, shorter than 32 characters, or equal.

## 14. Implemented vs missing security measures

| Implemented | Missing / partial |
| --- | --- |
| Hashed passwords, generic login errors, timing equalization | Password reset, account recovery, MFA |
| Server-validated sessions, rotation, replay detection | Session/device list UI; refresh token table cleanup |
| Role + ownership checks, 404 for foreign resources | Admin cannot disable accounts via API |
| CSRF/origin checks on cookie endpoints | Content-Security-Policy |
| Per-process rate limits | Shared/distributed rate limiting; per-account lockout |
| Coordinates hidden from admins/unrelated users | Location data retention policy (only latest kept) |
| Secrets validation at boot, unset bootstrap creds | Secret rotation procedure (rotating `USER_CODE_SECRET` changes OTPs; `JWT_SECRET` also signs QR tokens) |
| Non-root container user, `.dockerignore` excludes secrets | `pytest` and dev tooling shipped in prod image |
| Public `/health`, `/openapi.json`, `/docs` | These disclose configuration (provider, simulator flag) — low risk, but unauthenticated |

See [18 — Problems and improvements](18-problems-and-improvements.md#security) for recommendations.

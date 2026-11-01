# Persistent sign-in and logout

Sign-in creates a server session with a fixed 30-day lifetime. Access JWTs last at most 15 minutes and reference that session. The browser keeps access tokens in memory and restores them after reload using a single-use refresh cookie. No authentication credentials are stored in localStorage or sessionStorage.

The refresh cookie is HttpOnly, SameSite=Lax, scoped to `/api/v1/auth`, and Secure outside development. Only SHA-256 hashes of high-entropy refresh credentials are stored in the database. Refresh rotates the credential with a conditional database write. Reusing a consumed credential revokes its entire session, including its access tokens. If a refresh response is lost after the server rotates its credential, signing in again may be necessary.

The browser shares concurrent refresh attempts, uses Web Locks to serialize refresh-cookie changes across tabs where available, and renews access tokens before expiry. Authenticated API calls can refresh and retry once after a 401. Multiple tabs without Web Locks may require signing in again if their refresh requests race. Signing out broadcasts a notification to other tabs in the same browser. Other devices discover revocation on their next request or refresh; the server disconnects revoked sockets before delivering further events.

## Updating an existing installation

Stop Flask and Vite, pull the latest code, then run from the repository root:

```powershell
# Windows
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

```sh
# Linux / macOS
cd backend
.venv/bin/flask --app run db upgrade
.venv/bin/python run.py
```

Restart the frontend with `npm.cmd run dev` on Windows or `npm run dev` elsewhere. There are no new dependencies. The migration adds `auth_sessions` and `refresh_tokens`, preserving accounts and rides. Sign in again after upgrading: old access tokens do not contain a session ID and are intentionally rejected.

## Checking the feature

1. Sign in, then reload a rider, driver or admin page. The same account should be restored.
2. Open another tab in the same browser. Both tabs should restore sign-in.
3. Sign in using a private window as a separate device. Normal sign-out affects only its own server session.
4. Under **Your account**, use **Sign out all devices** and confirm. All of that account's access tokens and refresh credentials must stop working.
5. As an available driver, sign out and sign in again. The driver should be offline. With an assigned ride, sign-out keeps that ride; it is restored on the next sign-in, and the ride's OTP is still required to start it.
6. If logout cannot reach the server, an error appears and sign-out remains available for retry. The interface does not claim logout succeeded until the server confirms revocation.

## HTTP and deployment

- `POST /auth/refresh` uses the refresh cookie; returns `access_token`, `expires_in`, `expires_at` and `user`.
- `POST /auth/logout` uses the refresh cookie; works with an expired access token and is idempotent.
- `POST /auth/logout-all` requires a valid bearer access token and revokes every session for that user.
- Cookie session mutations require `X-Session-Request: 1`. Browser Origin must equal the request host origin or an exact origin listed in `AUTH_TRUSTED_ORIGINS`. Cross-site Fetch Metadata is rejected. Login also checks browser Origin; JSON-only login prevents form-based login CSRF. The API does not enable cross-origin credential sharing.
- Vite preserves the browser-facing Host for API requests. For a production reverse proxy that rewrites Host, set `AUTH_TRUSTED_ORIGINS` to the exact HTTPS frontend origin, such as `https://ridez.example`. Never put a wildcard in this list.
- Serve the frontend and API on the same HTTPS origin in production. Keep `JWT_SECRET` and `USER_CODE_SECRET` stable and configure the database as documented. Session credentials and Authorization headers must not be logged.
- Driver logout closes pending invitations and stops availability; it does not release an active ride or change a trip state. Other driver sessions refresh authoritative state through the existing notifications and reconciliation.

Automated backend tests use SQLite. They do not establish SQL Server concurrency behavior. Production still needs shared rate limiting, a shared Socket.IO broker, worker supervision, session-data retention maintenance and SQL Server integration checks.

Driver logout also clears the persisted stay-available-after-trip choice. Completing an already assigned trip from another valid session cannot silently undo that choice.

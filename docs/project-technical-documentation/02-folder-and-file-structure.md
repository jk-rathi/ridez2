# 02 — Folder and file structure (file-by-file)

[← Back to index](README.md) · Next: [03 — System architecture →](03-system-architecture.md)

This document explains **every tracked file** in the repository (120 files). For each source file it lists purpose, the important functions with inputs/outputs, dependencies, callers, the tables/APIs touched, and what breaks if it is changed or removed. Deeper walkthroughs of complex logic live in [04 — Frontend](04-frontend-documentation.md) and [05 — Backend](05-backend-documentation.md).

## Repository tree

```text
ridez.io/
├── .github/workflows/checks.yml     CI pipeline
├── .dockerignore  .gitignore  .node-version  .python-version
├── Dockerfile                       Multi-stage image (SPA build + Python runtime)
├── render.yaml                      Render Blueprint (1 Docker web service + disk)
├── requirements.txt                 Root shim → backend/requirements.lock
├── README.md  TEST_PAYMENTS.md      Human docs
├── backend/
│   ├── .env.example                 Backend env template (no secrets)
│   ├── requirements.txt             Direct dependencies
│   ├── requirements.lock            Full pinned dependency set (used everywhere)
│   ├── run.py                       Dev entry point (Socket.IO dev server + worker)
│   ├── wsgi.py                      Production WSGI entry (Gunicorn)
│   ├── gunicorn.conf.py             Gunicorn config + worker start hook
│   ├── app/                         Flask application package (23 modules)
│   ├── migrations/                  Alembic environment + 13 versions
│   └── tests/                       18 pytest modules
├── frontend/
│   ├── index.html  vite.config.js  package.json  package-lock.json  .env.example
│   ├── src/                         24 JS/JSX/CSS modules
│   └── tests/qr-session.browser.cjs Manual Playwright check
├── deploy/                          start.sh, render-build.sh, render-start.sh, smoke.py, backup.py
└── docs/                            Topic notes + this knowledge base
```

Untracked/generated directories you may see locally: `backend/instance/` (auto-generated dev secrets `jwt.key`, `codes.key` and the dev SQLite DB — git-ignored), `frontend/node_modules/`, `frontend/dist/`, `backend/frontend_dist/` (copied SPA build for native Render), `backend/.venv*`. All are ignored by `.gitignore`.

---

## Backend: `backend/app/`

The package follows a **routes → services → repositories → models** layering (documented in `docs/PRODUCT_BLUEPRINT.md`: "Keep controllers thin; services own business rules and repositories own persistence"). In practice some services also run queries directly.

### `backend/app/__init__.py` — application factory

**Purpose.** Creates and configures the Flask app. It is the single place where configuration, secrets validation, extensions, blueprints, real-time and CLI commands are wired together.

**Why it exists.** The factory pattern (`create_app(config)`) lets tests create isolated apps with in-memory databases and lets `run.py` and `wsgi.py` share configuration.

| Symbol | Signature / type | Responsibility |
| --- | --- | --- |
| `db` | `SQLAlchemy()` | Global Flask-SQLAlchemy handle imported everywhere as `from . import db` |
| `create_app` | `(config: dict \| None = None) -> Flask` | See logic below |
| CLI `init-db` | `flask --app run init-db` | `db.create_all()`; refuses outside development |
| CLI `check-routing` | `[--probe]` | Prints route provider and whether the Google server key is set / matches `backend/.env` (never prints the key). `--probe` makes one real `compute()` call |
| CLI `create-admin` | prompts `--mobile --name --password` (hidden, confirmed) | `services.register(..., role='admin', allow_admin=True)` |
| CLI `bootstrap-admin` | no args | `bootstrap.bootstrap_admin()` from `BOOTSTRAP_ADMIN_*` env vars |

**`create_app` logic, step by step**

1. `load_dotenv(backend/.env, override=False)` — real environment variables always win.
2. `development = APP_ENV == 'development'` (default `development`).
3. In development, if `JWT_SECRET` or `USER_CODE_SECRET` are missing, generate 32-byte hex secrets once into `instance/jwt.key` and `instance/codes.key` (opened with `'x'` mode and `0o600` permissions) and reuse them on restart — so sessions and account codes survive restarts.
4. Set `SQLALCHEMY_DATABASE_URI` (`DATABASE_URL`, default `sqlite:///ridez.db` only in development), `JWT_SECRET`, `USER_CODE_SECRET`.
5. Merge the `config` argument (tests use this).
6. `setdefault` feature flags from env: `TEST_PAYMENTS_ENABLED` and `SIMULATOR_ENABLED` (default on in development, off otherwise), `ROUTE_PROVIDER` (`simulator` in development, `google` otherwise; anything else raises), `GOOGLE_MAPS_SERVER_KEY`, `AUTH_COOKIE_SECURE` (= not development), `AUTH_TRUSTED_ORIGINS` (comma list), `REFRESH_SESSION_DAYS=30`, `LOCATION_STALE_SECONDS=90`, `MATCH_ROUND_SECONDS=30`, `MATCH_MAX_RADIUS_M` (default 5000; must be a multiple of 500 in 500–10000).
7. **Fail fast**: raise `RuntimeError` naming any missing `DATABASE_URL`/`JWT_SECRET`/`USER_CODE_SECRET`. Outside development also require both secrets ≥ 32 chars, distinct, and a Google server key when `ROUTE_PROVIDER=google`.
8. `TRUST_PROXY_HEADERS=1` wraps the WSGI app in `ProxyFix(x_for=1, x_proto=1)` (trust exactly one proxy — Render).
9. `SQLALCHEMY_ENGINE_OPTIONS.pool_pre_ping=True`.
10. `db.init_app`, `Migrate(app, db)`, import `routes`, `ride_routes`, `test_payment_routes` (the latter two **register routes on the same `api` blueprint as an import side-effect**), register blueprint at `/api/v1`, `init_realtime(app)`, `register_frontend(app)`.
11. App-level JSON handlers for 404 (`{"error":"Resource not found"}`) and 405.

**Used by:** `run.py`, `wsgi.py`, every test fixture, `migrations/env.py` (through Flask-Migrate).
**If removed/broken:** nothing starts. Changing defaults here changes behaviour globally (e.g. lowering `LOCATION_STALE_SECONDS` makes drivers drop out of matching sooner).

### `backend/app/models.py` — database schema (19 SQLAlchemy models)

**Purpose.** Declares every table, column, primary/foreign key and CHECK constraint, plus `public()` serializers that decide what JSON each entity exposes.

| Model (table) | Key methods | Notes |
| --- | --- | --- |
| `User` (`users`) | `public() -> dict` adds `vehicle` for drivers | CHECKs `valid_user_role`, `valid_user_status` (suspended only for drivers) |
| `DriverPresence` (`driver_presence`) | — | `available`, `resume_available` |
| `FareQuote` (`fare_quotes`) | `public()` → strings for money, `currency:'INR'`, `traffic_available`, `expires_at` + `Z` | Immutable fare snapshot |
| `FarePolicy` (`fare_policies`) | — | JSON `settings`, manual `version` PK |
| `Ride` (`rides`) | — | CHECK `valid_ride_state`; vehicle snapshot columns |
| `ActiveRide` (`active_rides`) | — | PK `user_id` = "one active ride per person" |
| `Invitation` (`ride_invitations`) | — | PK `(ride_id, driver_id)` = never invite a driver twice for the same ride |
| `DriverLocation` (`driver_locations`) | — | Latest fix only; `updated_at` indexed |
| `MatchRound` (`ride_match_rounds`) | — | PK `(ride_id, round_no)` |
| `OutboxEvent` (`outbox_events`) | — | `delivered_at` indexed |
| `RevenueLedger` (`revenue_ledger`) | `public()` adds `status:'ALLOCATED'` | PK `ride_id` = allocate once |
| `RevenueShareSetting` (`revenue_share_settings`) | `public()` | CHECK `valid_revenue_split` (sum = 100) |
| `AdminAudit` (`admin_audit`) | — | `details` JSON for vehicle edits |
| `AuthSession` (`auth_sessions`) | — | Revocable server session |
| `RefreshToken` (`refresh_tokens`) | — | PK = SHA-256 hex of the token |
| `DriverVehicle` (`driver_vehicles`) | `public()` | Optimistic `version` |
| `MockPayment` (`mock_payments`) | `public()` adds `test_only: True` | CHECK status |
| `RidePayment` (`ride_payments`) | `public()` | 3 CHECKs incl. "CONFIRMED needs method and confirmed_at" |
| `RideRating` (`ride_ratings`) | `public(include_comment=True)` | PK `(ride_id, rater_role)`; CHECK stars 1–5 |

**Used by:** every service and repository. **If modified:** must be accompanied by an Alembic migration; `/api/v1/ready` returns 503 until the DB is at the new head. Full field reference: [07 — Database](07-database-documentation.md).

### `backend/app/routes.py` — the `api` Blueprint, auth decorator, core endpoints

**Purpose.** Creates the `api` Blueprint and the cross-cutting HTTP machinery: JSON error responses, `no-store` caching, JSON body parsing, authentication/authorization decorator, the login/register rate limiter, and auth/health/doc endpoints.

| Symbol | Inputs → output | Responsibility |
| --- | --- | --- |
| `api` | `Blueprint('api')` | Mounted at `/api/v1` |
| `no_store(response)` | after_request | Adds `Cache-Control: no-store` to every API response |
| `api_error(error: ApiError)` | errorhandler | Returns `{"error": message}` with `error.status`; on 401 from `/auth/refresh` or `/auth/logout-all` also **clears the refresh cookie** |
| `body() -> dict` | request JSON | Raises `ApiError('A JSON object is required')` (400) unless the body is a JSON object |
| `authenticated(role=None)` | decorator factory | Requires `Authorization: Bearer …`, calls `session_service.authenticate`, sets `g.user`, `g.auth_claims`; 403 if `role` given and differs |
| `limit_auth()` | before_request | For POST `/auth/login` and `/auth/register`: sliding window of 10 attempts per 60 s per `request.remote_addr`, stored in `app.extensions['auth_attempts']` (in-memory) → 429 |
| `health()` | `GET /health` | `status`, `route_provider`, `matching_worker` (tick within 10 s), `simulator`, `storage` (`sqlite-development` or `sql-server` label) |
| `registration()` | `POST /auth/register` | `register(body())` → 201 `{user}` |
| `sign_in()` | `POST /auth/login` | `check_origin(require_header=False)` → `login()` → JSON + Set-Cookie |
| `me()` | `GET /me` | `{user}` |
| `driver()` | `GET /driver/overview` (driver) | Summary derived from `snapshot()` |
| `admin()` | `GET /admin/overview` (admin) | Full admin `snapshot()` |
| `specification()` | `GET /openapi.json` | Returns `spec.SPEC` |
| `docs()` | `GET /docs` | Swagger UI HTML loading assets from jsDelivr |
| `refresh_session()` / `logout_session()` / `logout_all_sessions()` | `POST /auth/refresh`, `/auth/logout`, `/auth/logout-all` | Delegate to `session_service` |
| `readiness()` | `GET /ready` | 200 only if `alembic_version` equals the migration head **and** the worker ticked in the last 10 s; else 503 |

**Imports:** `services` (ApiError, login, register); lazily `session_service`, `ride_service`, `spec`, Alembic.
**Used by:** `ride_routes.py` and `test_payment_routes.py` import `api`, `authenticated`, `body` from here.
**If removed:** every endpoint disappears; the auth decorator is the only authorization gate.

### `backend/app/ride_routes.py` — ride, driver and admin endpoints

**Purpose.** Thin HTTP adapters for rides, drivers, payments, ratings and admin settings. Each handler authenticates, parses the body, calls one service function and wraps the result in JSON.

| Handler | Route | Role | Calls |
| --- | --- | --- | --- |
| `workspace` | `GET /workspace` | any | `ride_service.snapshot(g.user)` |
| `quote` | `POST /fares/quotes` | rider | **inline limiter** 10/min per user id (`extensions['quote_attempts']`), then `ride_service.quote` → 201 |
| `book` | `POST /rides` | rider | `ride_service.book` → 201 |
| `details` | `GET /rides/<ride_id>` | any participant/admin | `expire()`, `accessible()`, `public()` |
| `availability` | `POST /driver/availability` | driver | `ride_service.availability` |
| `location` | `PUT /driver/location` | driver | `location_service.update` + `repo.commit()` |
| `accept` / `reject` | `POST /rides/<id>/accept`, `/reject` | driver | `ride_service.accept` / `reject` |
| `payment_method` | `POST /rides/<id>/payment-method` | rider | `payment_service.choose` |
| `confirm_cash` | `POST /rides/<id>/confirm-cash` | driver | `payment_service.confirm_cash` |
| `rate` | `POST /rides/<id>/rating` | rider or driver (403 for admin) | `rating_service.submit` |
| `progress` | `POST /rides/<id>/<action>` | any (checked in service) | `ride_service.move`; body required for `start`, optional for `cancel`, ignored otherwise |
| `approve` | `POST /admin/drivers/<int:id>/approve` | admin | `ride_service.approve` → `admin_service.change_driver_status` |
| `fare_settings` / `update_fare_settings` | `GET`/`PUT /admin/fare-settings` | admin | `fare_service.settings` / `save` |
| `revenue_share` / `update_revenue_share` | `GET`/`PUT /admin/revenue-share` | admin | `revenue_service.settings` / `save` |
| `admin_audit` / `admin_audit_detail` | `GET /admin/audit`, `/admin/audit/<category>/<identifier>` | admin | `admin_service.audit` / `audit_detail` |
| `admin_drivers` | `GET /admin/drivers` | admin | `admin_service.driver_list(request.args)` |
| `suspend_driver` / `reinstate_driver` | `POST /admin/drivers/<int:id>/suspend`, `/reinstate` | admin | `admin_service.change_driver_status` |
| `trip_map` | `GET /rides/<id>/map` | rider/driver | `trip_map_service.trip_map` |
| `update_driver_vehicle` | `PUT /admin/drivers/<int:id>/vehicle` | admin | `admin_service.save_driver_vehicle` |

The catch-all `/rides/<ride_id>/<action>` handles `depart`, `arrive`, `start`, `complete`, `cancel`. Werkzeug prefers static segments, so explicit routes like `/accept`, `/map`, `/test-payment` take precedence. **(inferred from Werkzeug routing rules; the tests exercise these routes.)**

**Used by:** imported for side effects in `create_app`. **If removed:** all ride/admin functionality returns 404.

### `backend/app/test_payment_routes.py` — mock QR payment endpoints

**Purpose.** Lets testers simulate an online payment by scanning a QR code. Never moves money.

| Symbol | Inputs → output | Responsibility |
| --- | --- | --- |
| `enabled()` | — | 404 `Test payments are disabled` unless `TEST_PAYMENTS_ENABLED` |
| `signer()` | → `URLSafeTimedSerializer(JWT_SECRET, salt='mock-qr-payment-v1')` | Signs ride IDs |
| `payment_for(token: str) -> MockPayment` | token | `loads(token, max_age=900)`; 410 if expired/invalid; 404 if no record |
| `create_test_payment(ride_id)` | `POST /rides/<id>/test-payment` (rider) | Owner + COMPLETED + not already paid by cash; insert `MockPayment` PENDING (race-safe); returns `{payment, path:'/test-payment/<token>', expires_in:900}` |
| `view_test_payment(token)` | `GET /test-payments/<token>` (no auth) | `{payment}` |
| `simulate_test_payment(token)` | `POST /test-payments/<token>` (no auth) `{status}` | Conditional update that never downgrades SUCCESS; on SUCCESS calls `payment_service.confirm(ride,'ONLINE')`; notifies rider+driver |

**Tables:** `mock_payments`, `ride_payments`, `rides`, `fare_quotes`, `outbox_events`.

### `backend/app/spec.py` — OpenAPI 3.0.3 document

**Purpose.** Builds the dict served at `/api/v1/openapi.json` (and rendered by `/api/v1/docs`). Defines `ERROR`, `USER` schemas, helper `operation(summary, fields=None, protected=False, status='200') -> dict`, and `SPEC`, which is **mutated incrementally** at import time as features were added (the version ends at `0.8.0`).

**Coverage gaps (verified):** the spec does not document `/rides/{id}/test-payment`, `/test-payments/{token}`, or response bodies (only `"Success"`). Treat this document set, not the OpenAPI file, as the complete reference.

### `backend/app/web.py` — serving the SPA

`register_frontend(app)` adds `GET /` and `GET /<path:path>` handlers that serve files from `FRONTEND_DIST` (`backend/frontend_dist` or `/app/frontend_dist` in Docker).

- Returns JSON 404 `Frontend build is not installed` if the folder does not exist (normal in local dev, where Vite serves the SPA).
- Rejects paths starting with `api`/`socket.io` or containing dot-segments (`.env`, `..`) → JSON 404.
- Unknown files fall back to `index.html` only for SPA routes: `login`, `register`, `rider/*`, `driver/*`, `admin/*`, `test-payment/*`. Everything else → 404.
- `assets/*` → `Cache-Control: public, max-age=31536000, immutable`; other files `no-cache`.
- An app-wide `after_request` adds security headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy` (`no-referrer` on `/test-payment/` so the capability token does not leak via Referer, otherwise `strict-origin-when-cross-origin`), `Permissions-Policy: geolocation=(self)`, `X-Frame-Options: DENY`, and HSTS when the request is HTTPS.

### `backend/app/bootstrap.py` — non-interactive admin creation

`bootstrap_admin() -> str`. Reads `BOOTSTRAP_ADMIN_MOBILE`, `BOOTSTRAP_ADMIN_PASSWORD` (required) and `BOOTSTRAP_ADMIN_NAME` (default `Admin`). If the mobile already belongs to a rider/driver → error (never promotes). If an inactive admin exists → error (never reactivates). If an active admin exists → no-op message. Otherwise `register(..., role='admin', allow_admin=True)`. Called by CLI `bootstrap-admin`, run from `deploy/start.sh` / `render-start.sh` when `BOOTSTRAP_ADMIN=1`.

### `backend/app/services.py` — auth service, error type, trip OTP

Despite the generic name, this module contains **account and OTP logic** plus the shared exception.

| Function | Inputs → output | Responsibility |
| --- | --- | --- |
| `ApiError(message: str, status: int = 400)` | exception | The only error type the API layer translates to JSON |
| `normalize(value) -> str` | raw mobile | `phonenumbers.parse(value, None)` (country code required), validity check, E.164 output; length ≤ 40 |
| `register(data: dict, allow_admin=False) -> User` | name, mobile, password, role | Validation, duplicate check (409), permanent code generation, password hash, insert (IntegrityError → 409) |
| `login(data: dict) -> (dict, str)` | mobile, password | Normalized generic failure `Mobile or password is incorrect` (401); constant-time-ish via dummy hash; rejects `disabled`; delegates to `session_service.issue` |
| `trip_otp(ride) -> str` | Ride | `HMAC-SHA256(USER_CODE_SECRET, "trip-otp:v2:{ride.id}") mod 1 000 000`, zero-padded to 6 digits |
| `verify_trip_otp(ride, driver_id, value) -> None` | Ride, int, str | 5 failed attempts per driver per 60 s (in-memory, `extensions['trip_otp_attempts']`) → 429; validates 6 ASCII digits; `hmac.compare_digest`; wrong code → 400 |

**Used by:** `routes.py`, `bootstrap.py`, `__init__.py` CLI, `ride_service.py`, every service (for `ApiError`).

### `backend/app/repositories.py` — user repository

Four tiny functions on `users`: `by_mobile(mobile) -> User|None`, `by_id(user_id) -> User|None`, `code_exists(code) -> bool`, `save(user) -> User` (add + commit). Used by `services.register/login` and `bootstrap`. (`by_id` is currently unused — verified by search.)

### `backend/app/session_service.py` — sessions, tokens, CSRF/origin checks

**Purpose.** Everything about server-side sessions: issuing JWTs, rotating refresh cookies, verifying bearer tokens, revoking sessions and stopping a driver's work on logout.

| Function | Inputs → output | Responsibility |
| --- | --- | --- |
| `COOKIE='ridez_refresh'`, `COOKIE_PATH='/api/v1/auth'` | constants | Cookie is only sent to auth endpoints |
| `now()` | → naive UTC datetime | |
| `digest(value) -> str` | token | SHA-256 hex; only hashes are stored |
| `check_origin(require_header=True)` | request | 403 unless `X-Session-Request: 1` (when required); `Origin`, if present, must equal the host URL or one of `AUTH_TRUSTED_ORIGINS`; `Sec-Fetch-Site: cross-site` → 403 |
| `cookie(response, token=None) -> response` | | Sets or deletes the refresh cookie (HttpOnly, SameSite=Lax, Secure per config, max-age 30 days) |
| `payload(user, session) -> dict` | | JWT `{sub, sid, iat, exp}` HS256, `exp = min(now+15 min, session.expires_at)`; returns `access_token, expires_in, expires_at, user` |
| `new_refresh(session) -> str` | | `secrets.token_urlsafe(48)`; stores hash in `refresh_tokens` |
| `issue(user) -> (dict, str)` | | Creates `auth_sessions` row (30 days) + first refresh token, commits |
| `valid_session(session_id, user_id=None) -> AuthSession \| None` | | Exists, not revoked, not expired, belongs to user |
| `authenticate(token) -> (User, claims)` | JWT | Decode with required claims; user exists, not disabled; session valid → else 401 `Please sign in again` |
| `stop_requests(user_id)` | | For drivers: no-op lock UPDATE, `available=False, resume_available=False`, PENDING invitations → `CLOSED`, notify |
| `revoke(session)` | | `revoked_at = now`, `stop_requests` |
| `refresh() -> (dict, str)` | cookie | Look up hash; invalid → revoke + 401; **conditional** `used_at` update → replay detection revokes session; else issue new refresh token |
| `logout(user=None, all_devices=False)` | | All devices: revoke all user's sessions. Else find session via cookie, falling back to the Bearer token's `sid`. Then `disconnect_invalid()` |

**Tables:** `auth_sessions`, `refresh_tokens`, `users`, `driver_presence`, `ride_invitations`, `outbox_events`.

### `backend/app/ride_repository.py` — ride persistence helpers

**Purpose.** Persistence primitives for rides, invitations, presence, outbox and locks. Most return `bool` from `rowcount == 1` so callers know whether a conditional write won.

| Function | Inputs → output | Responsibility |
| --- | --- | --- |
| `get(model, key)` / `add(record)` / `commit()` / `rollback()` | | Session shortcuts |
| `notify(*user_ids)` | ints | Inserts one `OutboxEvent` per distinct id **plus one with `user_id=None`** (admins room) |
| `notify_ride(ride)` | Ride | Notifies rider, every invited driver and the assigned driver |
| `all_rides(user) -> list[Ride]` | | Rider: own; driver: assigned; admin: all. Newest 100 |
| `eligible_drivers(at) -> list[DriverPresence]` | datetime | Available, status active, `fresh` location with `recorded_at` and `updated_at` within `LOCATION_STALE_SECONDS`, and **not** in `active_rides` |
| `transition(ride_id, old, new, **values) -> bool` | | `UPDATE rides SET status=new … WHERE id AND status=old` |
| `assign(ride_id, driver_id, now, vehicle=None) -> bool` | | Single conditional UPDATE to ASSIGNED that re-checks: ride SEARCHING & unexpired, PENDING unexpired invitation for this driver, driver available+active+fresh; copies vehicle snapshot |
| `release(ride_id)` | | `DELETE FROM active_rides WHERE ride_id` |
| `close_invitations(ride_id, status='EXPIRED')` | | PENDING → status |
| `expire_round(ride, at) -> bool` | | Claims an overdue round by bumping `round_no` only if `round_no` and `expires_at` are unchanged (idempotent across worker/requests) |
| `round_for(ride)` | | `MatchRound` for current round |
| `expired_searches(now)` | | SEARCHING rides with `expires_at <= now` |
| `invitations(driver_id)` | | Rides with a PENDING invitation for the driver and still SEARCHING |
| `ledger(driver_id)` | | Driver's `RevenueLedger` rows |
| `drivers()` | | Newest 100 drivers |
| `ride_for_quote(quote_id)` | | Idempotency lookup |
| `set_available(driver_id, available, resume_available=None) -> DriverPresence` | | Upsert presence |
| `lock_active_driver(driver_id, require_available=False) -> bool` | | **No-op UPDATE** `status_revision = status_revision` on an active driver row — acquires a row/DB write lock so availability, acceptance and suspension serialize; returns False if the driver is not active (or not available when required) |
| `lock_driver(driver_id) -> bool` | | Same lock regardless of status |

### `backend/app/ride_service.py` — ride business logic

**Purpose.** The core domain service: quotes, bookings, availability, acceptance, rejection, trip transitions, cancellation and the workspace snapshot.

| Function | Inputs → output | Responsibility |
| --- | --- | --- |
| `now()` / `money(value)` | | UTC now; Decimal rounded half-up to 0.01 |
| `simulator()` | | 503 if provider is `simulator` and `SIMULATOR_ENABLED` is off |
| `text(data, key, limit=160) -> str` | | Required trimmed string of 1..limit chars |
| `quote(user, data) -> dict` | rider, body | Validate → `expire()` → `route_provider.compute` → `fare_service.calculate` → insert `FareQuote` (5 min) → `public()` + `polyline` |
| `expire()` | | `matching.advance()` then `db.session.expire_all()` — every request catches up overdue deadlines itself |
| `accessible(user, ride_id) -> Ride` | | Participant or admin, else 404 (not 403, to avoid revealing existence) |
| `public(ride, user, invitation=False) -> dict` | | Role-aware ride JSON: quote, driver (name, code, vehicle snapshot, rating), rider (name, rating), test/real payment, cancellation, my_rating (participants), ratings (admin), settlement (driver/admin only, not in invitations) |
| `book(user, data) -> dict` | `{quote_id}` | Idempotent booking + first matching round |
| `availability(user, data) -> dict` | `{available, latitude…}` | Go online/offline; stores next-trip preference while busy |
| `accept(user, ride_id) -> dict` | | Guarded conditional assignment |
| `reject(user, ride_id) -> dict` | | PENDING → REJECTED (idempotent) |
| `cancellation(ride, user) -> dict` | | `{by, by_you, reason, cancelled_at}` |
| `move(user, ride_id, action, data=None) -> dict` | | `cancel` and driver transitions `depart/arrive/start/complete`; completion side-effects |
| `snapshot(user) -> dict` | | The `/workspace` payload (role-specific) |
| `approve(user, driver_id, data)` | | Delegates to `admin_service.change_driver_status(..., 'approve', ...)` |

Walkthroughs: [05 — Backend](05-backend-documentation.md#5-ride-service-ride_servicepy).

### `backend/app/matching.py` — expanding-radius matching

| Function | Responsibility |
| --- | --- |
| `invite(ride, started_at)` | Records a `MatchRound`; if the round is still open and the quote has pickup coordinates, invites every eligible driver within `ride.radius_m` (haversine) who was **not invited before** for this ride, after `lock_active_driver(require_available=True)` succeeds |
| `advance()` | Up to `MATCH_MAX_RADIUS_M//500 + 1` catch-up passes: claim each overdue round, expire its invitations, then either end in `NO_DRIVER_FOUND` (max radius reached) or expand radius by 500 m with a new deadline = old deadline + 30 s and invite again. Finally marks stale driver locations `fresh=False` and notifies those drivers |
| `close_round(ride, outcome)` | Sets the current round's `outcome` (`ASSIGNED`, `CANCELLED`) |

Called from `ride_service.expire/book/accept/move` and `realtime.tick`.

### `backend/app/location_service.py` — GPS validation

| Function | Inputs → output | Responsibility |
| --- | --- | --- |
| `utcnow()` | | Naive UTC now (used across modules) |
| `coordinate(value, name, bound) -> float` | number | Finite, not bool, `abs ≤ bound` |
| `distance_m(lat1, lng1, lat2, lng2) -> float` | | Haversine metres (Earth radius 6 371 000 m) |
| `is_fresh(location, at=None) -> bool` | | `fresh` flag and both `recorded_at` and `updated_at` newer than 90 s |
| `public(location) -> dict` | | `{fresh, recorded_at, accuracy_m}` — **no coordinates** |
| `update(user, data, initializing=False) -> dict` | | Status/permission rules, coordinate/accuracy/time validation, ordering, implausible-movement check, replay no-op, upsert, notify |

### `backend/app/route_provider.py` — routing adapter

| Function | Responsibility |
| --- | --- |
| `denial_reason(response) -> str \| None` | Extracts an allow-listed Google error reason (e.g. `API_KEY_INVALID`, `BILLING_DISABLED`) without leaking other vendor text |
| `seconds(value) -> int` | Parses Google duration strings like `"1234.5s"` → ceil seconds; must be 1..604 800 |
| `compute(pickup, destination, labels) -> dict` | Returns `{provider, distance_m, duration_seconds, baseline_seconds, polyline}`. Simulator: deterministic from SHA-256 of labels. Google: `POST computeRoutes`, timeout (3 s connect, 10 s read), no redirects; maps 429/401/403/other/timeout/connection errors to specific `ApiError`s; validates every field |

Used by `ride_service.quote`, `trip_map_service`, CLI `check-routing`.

### `backend/app/fare_service.py` — fare policy and calculation

| Symbol | Responsibility |
| --- | --- |
| `DEFAULT_POLICY` | ₹40 base, ₹12/km, ₹2/min, ₹40 minimum, `Asia/Kolkata`, all surge off, cap 2.00×, traffic threshold 1.25 / multiplier 1.25, demand threshold 2.00 / multiplier 1.25 / min 5 requests, no zones |
| `current() -> (version, policy)` | Latest `FarePolicy` or `(0, DEFAULT_POLICY copy)` |
| `decimal_field(data, key, low='0', high='100000') -> str` | Strict 2-dp decimal validation |
| `validate(data) -> dict` | Validates a full policy incl. ≤ 20 zones (id, name, lat/lng, radius 100–50 000 m, multiplier 1–5, distinct weekdays 0–6, HH:MM start/end, enabled) |
| `settings() -> dict` | `{version, policy, history[≤20]}` |
| `save(user, data) -> dict` | Optimistic version check, insert `version+1`, notify admins |
| `scheduled(zone, local) -> bool` | Day/time window incl. overnight windows and all-day (`start == end`) |
| `demand_signal(pickup, at) -> (requests, ratio)` | Open SEARCHING requests within 1 km ÷ max(1, fresh eligible drivers within 1 km) |
| `calculate(route, pickup, at=None) -> dict` | Itemized fare; highest eligible multiplier capped at `max_multiplier`; reason text; `rate_snapshot` JSON; 422 if total > 99 999 999.99 |

### `backend/app/revenue_service.py` — revenue split

| Function | Responsibility |
| --- | --- |
| `active(at=None) -> dict` | Split in force at `at` (latest `effective_from ≤ at`, ties → highest version) or default `{version:0, 85.00/15.00}` |
| `revision() -> int` | Highest version (0 if none) |
| `settings() -> dict` | `{version, active, upcoming[], history[≤100], server_time}` |
| `percentage(value) -> Decimal` | 0–100, ≤ 2 dp |
| `save(user, data) -> dict` | Version check, sum = 100, reason, optional future `effective_from` (tz-aware, ≤ 366 days), records previous split |
| `allocate(ride, quoted, driver_id, completed_at) -> RevenueLedger` | `driver_amount = round_half_up(total × pct / 100)`, `company_amount = total − driver_amount` |

### `backend/app/payment_service.py` — per-ride payment

| Function | Responsibility |
| --- | --- |
| `record_completion(ride, quoted, at)` | Insert `RidePayment` PENDING, amount = quote total |
| `notify(ride)` | Outbox events for rider + driver |
| `completed_ride(ride_id) -> (Ride, RidePayment)` | 409 unless ride COMPLETED with a payment row |
| `choose(user, ride_id, data) -> dict` | Rider sets `CASH`/`ONLINE` while PENDING; ONLINE needs test payments enabled; idempotent |
| `confirm(ride_id, method, by=None) -> int` | Conditional `PENDING → CONFIRMED`; returns rowcount (first wins) |
| `confirm_cash(user, ride_id) -> dict` | Assigned driver confirms cash; 409 if already paid online |
| `confirmed_by_other_method(ride_id) -> bool` | Confirmed with a method other than ONLINE |

### `backend/app/rating_service.py` — ratings

`TAGS` (rider→driver tags and driver→rider tags), `summary(user_id) -> {average: '4.5'|None, count}`, `given(ride_id, role)`, `for_admin(ride_id) -> list` (with comments), `submit(user, ride_id, data) -> dict` (validation, final once submitted, idempotent same-stars retry).

### `backend/app/admin_service.py` — admin operations

| Function | Responsibility |
| --- | --- |
| `metrics() -> dict` | Ride counts by status, fresh vs stale available drivers, pending/suspended drivers, all-time allocation sums |
| `events()` | `UNION ALL` subquery normalizing `admin_audit`, `fare_policies`, `revenue_share_settings` into `{id, category, action, actor_id, created_at, reason, target}` |
| `audit(params) -> dict` | Paginated (20/page, page ≤ 100 000), category filter, escaped `ILIKE` search over reason/admin name/action |
| `audit_detail(category, identifier) -> dict` | Human-readable before/after rows (status, vehicle, revenue split, fare policy diff) |
| `DRIVER_TRANSITIONS` | `approve: pending→active`, `suspend: active→suspended`, `reinstate: suspended→active` |
| `change_driver_status(actor, driver_id, action, data) -> dict` | Versioned, idempotent status change + audit + `stop_requests` |
| `driver_list(params) -> dict` | Paginated filterable driver list with location freshness, active ride, rating |
| `save_driver_vehicle(actor, driver_id, data) -> dict` | Versioned vehicle upsert + audit |

### `backend/app/realtime.py` — Socket.IO and the background worker

| Symbol | Responsibility |
| --- | --- |
| `socketio` | `SocketIO(async_mode='threading')` |
| `init_realtime(app)` | Binds Socket.IO; registers `connect` (authenticate `auth.token`, join `user:{id}` and `admins` for admins; reject otherwise) and `disconnect` handlers; tracks connections in `extensions['ride_connections']` |
| `disconnect_invalid()` | Drops sockets whose JWT expired, user is disabled/missing, or session is revoked |
| `dispatch()` | Emit up to 200 undelivered outbox events as `workspace.changed`, mark delivered, prune delivered events older than 7 days |
| `tick(app)` | `advance()` + `dispatch()` in an app context; records `matching_last_tick` |
| `start_worker(app)` | Starts the 1-second loop once per process |

### `backend/app/trip_map_service.py` — live trip map

`ACTIVE` and `APPROACH` status sets; `phase_for(ride)`; `source_for(phase, driver)`; `cached_route(key, compute)` (thread-safe in-memory cache with `concurrent.futures.Future` to coalesce concurrent Google calls, 60 s TTL for success / 10 s for errors, ≤ 256 entries, 15 s wait timeout); `position(ride)` (fresh driver coordinates or None); `trip_map(user, ride_id) -> dict`.

---

## Backend entry points and configuration

| File | Purpose | Details |
| --- | --- | --- |
| `backend/run.py` | **Development** entry | `create_app()`, `start_worker(app)`, `socketio.run(host='0.0.0.0', port=$PORT or 5000, use_reloader=False, allow_unsafe_werkzeug=True)`. Also the `--app run` target for Flask CLI commands locally |
| `backend/wsgi.py` | **Production** WSGI entry | `app = create_app()`; worker startup is left to Gunicorn's hook |
| `backend/gunicorn.conf.py` | Gunicorn settings | `bind 0.0.0.0:$PORT (10000)`, `workers = 1` (comment: matching loop and socket dispatcher require exactly one process), `worker_class = 'gthread'`, `threads = 100`, `preload_app = False`, `timeout 60`, `graceful_timeout 30`, `keepalive 5`, `accesslog = None` (don't log URLs with Socket.IO session IDs), `post_worker_init` → `start_worker(worker.wsgi)` |
| `backend/.env.example` | Template | Variable names and comments only; copy to `backend/.env` |
| `backend/requirements.txt` | Direct deps | 12 packages |
| `backend/requirements.lock` | Full pin set (35 packages) | Used by Docker, CI, README and root `requirements.txt` |

## Backend migrations: `backend/migrations/`

| File | Purpose |
| --- | --- |
| `env.py` | Standard Flask-Migrate Alembic environment; uses the app's engine and metadata; suppresses empty autogenerate revisions |
| `alembic.ini` | Logging configuration only |
| `script.py.mako` | Template for new revisions |
| `README` | One line: "Single-database configuration for Flask." |
| `versions/*.py` | 13 linear revisions, head `c51e8a2f90d4`. Full table in [07 — Database](07-database-documentation.md#7-migrations) |

## Backend tests: `backend/tests/`

All tests use pytest with the `app`/`client` fixtures from `test_auth.py` (in-memory SQLite, simulator mode, fixed test secrets) and the `actors` fixture from `test_rides.py` (two riders, two drivers, one admin, all logged in). Concurrency tests create file-backed SQLite databases under `tmp_path` and race real threads with `threading.Barrier`. Google calls are mocked with `unittest.mock.patch('app.route_provider.requests.post')`.

| Module | What it verifies |
| --- | --- |
| `test_auth.py` | Registration, E.164 duplicate detection, validation, generic login errors, disabled accounts, role authorization, admin provisioning only via CLI, invalid/expired tokens, auth rate limit, JSON validation, docs endpoints |
| `test_sessions.py` | Refresh rotation and hashing, replay revocation, logout vs logout-all, CSRF/origin checks, cross-site login rejection, expired access refresh, driver logout stopping matching but keeping the active ride, Secure cookie in production, concurrent refresh with one winner, persistence across app instances, Bearer fallback logout |
| `test_rides.py` | Full ride + exactly-once settlement, quote validation/ownership/expiry/idempotent booking, invitation expiry/reject/cancel, permissions, simulator disabled, concurrent acceptance has one winner |
| `test_matching.py` | Location validation, replay/implausible movement, stale exclusion, radius expansion invites only new drivers, worker recovery of overdue rounds, socket auth/scoping/reconnect, socket expiry disconnect, outbox retry, recovery from a new app instance |
| `test_cancellation.py` | Pre-trip cancellation for each phase/actor, reasons, mid-trip rejection, notice expiry, race outcomes, expired search not relabelled |
| `test_driver_auto_availability.py` | Staying available after completion, offline preference, fresh-GPS requirement, ineligible conditions, retries, offline vs completion race |
| `test_driver_review.py` | Suspend/reinstate, trip preservation, version/reason validation, audit immutability, search/pagination with literal wildcards, concurrent admins, suspension vs availability/acceptance races |
| `test_vehicle_details.py` | Vehicle save/snapshot, history immutability, validation, admin-only audit, missing vehicle explicit, edit vs acceptance consistency |
| `test_google_fares.py` | Google request shape, no fallback on errors, connection failures, missing key, malformed responses, policy validation/conflicts, surge overlap/cap/minimum, timezone/overnight zones, traffic and demand surge, quote rate limit, denial reason handling, `check-routing` CLI |
| `test_trip_map.py` | Route restore for both roles without repricing, phase switches, stale fallback, participant-only access, errors, no driver coordinates after completion, cache expiry and thread coalescing, approach routing |
| `test_revenue.py` | Defaults/permissions, invalid splits, effective-dated snapshots, boundaries, rounding extremes, same-timestamp ordering, concurrent admins |
| `test_ride_payments.py` | Pending payment at completion, cash flow, online success blocking cash and vice-versa, permissions, unavailable before completion |
| `test_mock_payments.py` | Mock QR idempotent success, financial isolation, access/expiry/disable, notifications |
| `test_ratings.py` | Two-way averages, comment privacy, finality/validation, participant-only, rider rating shown on invitations |
| `test_trip_otp.py` | Per-ride private code, required at start, previous ride code rejected, attempt limit, leading zero |
| `test_admin_privacy.py` | Riders never receive the split, admin metrics, audit access/filters/details/pagination |
| `test_bootstrap.py` | Bootstrap creates admin once, never logs credentials, never promotes/reactivates, names missing settings |
| `test_deployment.py` | SPA deep links and API boundaries, readiness, production config validation, proxy/secure cookie/origin/headers |

---

## Frontend: `frontend/`

### Configuration files

| File | Purpose |
| --- | --- |
| `package.json` | Name `ridez-web`, `type: module`. Scripts: `dev` = `vite --host 0.0.0.0`, `build` = `vite build`, `preview` = `vite preview --host 0.0.0.0` |
| `package-lock.json` | Exact npm dependency tree (used by `npm ci` in Docker/CI) |
| `vite.config.js` | React plugin; dev proxy `/api` → `API_PROXY_TARGET` (default `http://127.0.0.1:5000`, `changeOrigin:false` so the Host/Origin match for session origin checks) and `/socket.io` with `ws:true` |
| `index.html` | Root `<div id="root">`, loads `/src/main.jsx`, theme colour, title |
| `.env.example` | `VITE_GOOGLE_MAPS_BROWSER_KEY`, `VITE_GOOGLE_MAP_ID` (copy to `.env.local`). Warns never to put the server key in a `VITE_` variable |

### `frontend/src/main.jsx` — app shell, routing, auth context

| Component / symbol | Responsibility |
| --- | --- |
| `Auth` context + `AuthProvider` | Holds `session`, `ready`, `restoreError`, `retryRestore`, `logout`, `signingOut`, `logoutError`. On mount subscribes to `authSession` and calls `refreshSession()` to restore from the cookie. Schedules a renewal 60 s before `expires_at` (min 1 s), retrying every 15 s on failure |
| `SessionLoading`, `Brand`, `Tag`, `PageHeading` | Presentational helpers |
| `Landing`, `CityMap` | Public marketing page with an illustrative SVG map (explicitly not live) |
| `AuthPage({register})` | Login/register form. Registration: `api('/auth/register')` and shows the permanent code. Login: `signIn(fields)` then `navigate('/{role}')`. Role preselected from `?role=driver` |
| `Protected({role})` | Waits for restore; shows restore error with retry; redirects to `/login` if no session, or to own workspace on role mismatch |
| `navItems` | Sidebar items per role |
| `Workspace({role})` | Sidebar + nested routes (see [diagrams/frontend.md](diagrams/frontend.md)) |
| `Account({user})` | Profile fields + "Sign out all devices" |
| `ComingSoon` | Fallback for unknown sub-routes |
| `App` | Top-level routes |

**If removed:** the app does not render. **Calls:** `/auth/register`, plus everything via `authSession`.

### `frontend/src/api.js` — HTTP client

`api(path, {token, ...fetchOptions}) -> Promise<object>`:
1. `resolveToken(token)` maps a possibly-stale token captured by a component to the **current** session token (throws if the token never belonged to this session — prevents using another user's token after a switch).
2. `fetch('/api/v1' + path, {credentials:'same-origin', headers:{'Content-Type':'application/json', Authorization:'Bearer …'}})`.
3. On 401 (and not aborted): use the already-renewed session if another request refreshed it, otherwise `refreshSession()`, then retry once.
4. Parse JSON (error if unreadable); throw `Error(data.error)` if `!response.ok`; return data.

Used by every component that talks to the backend except the auth calls in `authSession.js`.

### `frontend/src/authSession.js` — session store

Module-level store: `session`, `pendingRefresh`, `generation`, `signingOut`, `listeners`, `knownTokens`, and a `BroadcastChannel('ridez-auth')`.

| Export | Responsibility |
| --- | --- |
| `currentSession()` | Current `{access_token, expires_in, expires_at, user}` or null |
| `subscribeSession(listener) -> unsubscribe` | Used by `AuthProvider` |
| `resolveToken(token)` | See `api.js` |
| `refreshSession() -> Promise` | Single-flight (`pendingRefresh`), cross-tab serialized with `navigator.locks.request('ridez-refresh-cookie')`, ignores results from an older `generation`, publishes null on 401 |
| `signIn(fields)` | `POST /auth/login` under the lock; bumps generation; publishes |
| `signOut(allDevices=false)` | For all devices: refresh first (to get a valid Bearer), then `POST /auth/logout-all`; otherwise `POST /auth/logout`; publishes null; broadcasts `signed-out` to other tabs |

Internal `request(path, body, token)` always sends `X-Session-Request: 1` (required by the backend CSRF check).

### `frontend/src/RideWorkspace.jsx` — the main role workspace

The largest component; renders rider, driver and admin dashboards from one `/workspace` snapshot.

| Symbol | Responsibility |
| --- | --- |
| `currency`, `labels`, `actions` | INR formatter; status labels; next driver action per status |
| `useWorkspace(token)` | Opens an authenticated Socket.IO connection (`io({auth:{token}, transports:['polling','websocket']})`); on `workspace.changed` dedupes `event_id` (last 100) and debounces refresh by 80 ms; polls `/workspace` every 15 s when connected or 2 s when not; exposes `data, error, refresh, connection, updateAvailability` |
| `Countdown({deadline})` | Seconds remaining, ticking every 500 ms |
| `QuoteDetails({quote})` | Itemized fare rows (base, distance, time, minimum adjustment, surge) and provider description |
| `RideCard(...)` | One ride: status, cancellation notice, assigned details or quote, search progress, OTP input (driver at WAITING), next driver action button (with confirm before complete), cancel control, settlement (driver/admin), payment status, rating form (within 7 days), admin ratings, test payment card |
| `ActiveRidePanel(...)` | `useTripRoute` shared between `TripStatsCard` and `TripRouteMap` (Google rides only) |
| `RATING_WINDOW_MS` | 7 days (frontend-only rule) |
| `paymentDismissed`/`rememberPaymentDismissed` | `sessionStorage` key `ridez.payment-dismissed.{id}` |
| `usePaymentPrompt(role, data)` | For riders: opens the payment modal when the active ride disappears and turned into a COMPLETED/PENDING-payment ride, or on first load if the latest ride completed < 30 min ago |
| `RideWorkspace({role, user, token, view})` | Composes everything; `perform(path, body)` is the single POST helper (busy lock, error display, availability patch, refresh); `changeDriverAvailability(available)` gets a GPS fix first when going online |

### `frontend/src/BookingPanel.jsx`

Rider booking form. State: `form` (labels and coordinate strings), `quote`, `error`, `locating`. `change` clears coordinates when an address label is edited in Google mode; `select(prefix, point)` sets coordinates (from AddressSearch, map clicks or "Use my location"); `submit` validates required coordinates (both in Google mode, pickup only in simulator mode) and calls `perform('/fares/quotes', payload)`; "Confirm ride" calls `perform('/rides', {quote_id})`. Renders `GoogleRouteMap` (picker mode with the quote polyline) in Google mode.

### `frontend/src/AddressSearch.jsx`

Accessible combobox for Google Places (New) autocomplete. Debounces 300 ms, needs ≥ 3 chars, uses an `AutocompleteSessionToken` per search session (billing best practice), biases results to 50 km around the pickup, shows ≤ 5 suggestions, supports Arrow/Enter/Escape keys, and on choice calls `placePrediction.toPlace().fetchFields(['formattedAddress','location'])`. Uses sequence counters to drop stale async results. Shows "Powered by Google" attribution.

### `frontend/src/googleMaps.js`

`loadMaps() -> Promise<google.maps>` loads the Maps JS script once (`v=quarterly`, `libraries=marker,geometry`, `loading=async`, callback `__ridezGoogleReady`), with a 15 s timeout, `gm_authFailure` hook that dispatches `ridez.maps.error`, and clear errors when `VITE_GOOGLE_MAPS_BROWSER_KEY` is missing.

### `frontend/src/GoogleRouteMap.jsx`

Renders a Google map (default centre Mumbai 19.076, 72.8777). Props `pickup`, `destination`, `polyline`, `driverPosition`, `onSelect`. With `onSelect` it is a **picker** (toggle pickup/destination, click to set). Draws `P`/`D` `AdvancedMarkerElement`s, decodes the encoded polyline with `geometry.encoding.decodePath`, fits bounds, and moves a 🚕 driver marker. Retry button re-initializes on error.

### `frontend/src/TripRouteMap.jsx`

`tripPhase(ride)` (`approach`/`in_progress`/`overview`), `useTripRoute(ride, token)` (polls `/rides/{id}/map` at `refresh_after_seconds`, 15 s after errors; keyed by ride id + phase), and `TripRouteMap` (headings per phase/role, refresh button, error text, summary of driver location time).

### `frontend/src/TripStatsCard.jsx`

`googleNavigationUrl(place, lat, lng)` builds a `https://www.google.com/maps/dir/?api=1&destination=…&travelmode=driving&dir_action=navigate` link. `liveRoute()` turns map data into minutes/km/arrival time only when the route originates from the driver and targets the expected point. `TripStatsCard` shows phase-specific metrics (approach, waiting, in-progress) and a "Navigate in Google Maps" button for drivers.

### `frontend/src/useDriverLocation.js`

`getPosition()` — requires a secure context; tries high accuracy (15 s), then low accuracy (20 s) unless permission was denied; maps error codes 1/2/3 to friendly messages; returns `{latitude, longitude, accuracy_m, recorded_at}`. `useDriverLocation({token, enabled, available, onTrip})` — sends `PUT /driver/location` immediately then every 30 s (10 s on a trip); watches the Permissions API and, if permission is denied/revoked, posts `available:false` to stop new requests while keeping any active trip.

### Smaller components

| File | Responsibility | Backend calls |
| --- | --- | --- |
| `AssignedRideDetails.jsx` | Prominent card after acceptance: other person + rating, car plate/model/colour (or explicit "not provided"), fare, rider OTP before start, pickup/destination | — |
| `CancelRideControl.jsx` | Two-step cancel with role-specific preset reasons, "Other" requires text, max 200 chars typed; builds `"Reason — notes"` | `POST /rides/{id}/cancel` via `perform` |
| `CancellationNotice.jsx` | Who cancelled (you / driver / rider), reason, time, "no payment or refund" note | — |
| `DriverManagement.jsx` | Admin driver list with status filter, search, pagination, approve/suspend/reinstate review form with reason, vehicle editor launch | `GET /admin/drivers`, `POST /admin/drivers/{id}/{action}` |
| `VehicleEditor.jsx` | Car number/model/colour + reason form | `PUT /admin/drivers/{id}/vehicle` |
| `FareSettings.jsx` | Edit all policy fields, surge zones (add/remove, weekdays, times), reason; shows history | `GET`/`PUT /admin/fare-settings` |
| `RevenueSettings.jsx` | Driver/company percentages (must total 100), optional scheduled date (browser time → UTC ISO), reason; upcoming and history | `GET`/`PUT /admin/revenue-share` |
| `AdminAudit.jsx` | Category/search filters, pagination, expandable before/after detail | `GET /admin/audit`, `GET /admin/audit/{category}/{id}` |
| `OtpInput.jsx` | Six single-digit inputs with paste, backspace, arrow/home/end navigation; reports the joined string | — |
| `PaymentStatus.jsx` | `paymentLabel`, `PaymentStatusLine`, `DriverCollectCard` ("Cash received"), `usePaymentConfirmedFlash` (detects PENDING→CONFIRMED transitions), `PaymentConfirmedFlash` | `POST /rides/{id}/confirm-cash` via `perform` |
| `Rating.jsx` | `RatingTags` context (tags come from the server), `RatingBadge`, `StarsShown`, `RatingForm` (stars, sentiment-filtered tags, comment) | `POST /rides/{id}/rating` |
| `TestPayment.jsx` | `useTestQr` (create QR), `TestPaymentCard` (in ride cards), `TestPaymentPage` (public `/test-payment/:token` page), `PaymentSuccess`, `PaymentPrompt` (rider modal: choose cash/online, QR, failure retry, success + rating) | `POST /rides/{id}/test-payment`, `GET/POST /test-payments/{token}`, `POST /rides/{id}/payment-method` |
| `styles.css` | All styling (single global stylesheet) | — |

### `frontend/tests/qr-session.browser.cjs`

Manual Playwright script (not in CI) that mocks the API, signs in, renders `RideWorkspace` in history view, and asserts that generating a test QR with an expired access token triggers exactly one refresh and a retry with the new token. It hard-codes default paths (`/opt/codex/...playwright`, `/usr/bin/chromium`) overridable by `PLAYWRIGHT_MODULE`/`CHROMIUM_PATH`, and requires a running Vite server at `RIDEZ_TEST_URL`.

---

## Root and deployment files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Stage `frontend`: `npm ci` (optional proxy CA secret), build with `VITE_GOOGLE_MAPS_BROWSER_KEY`/`VITE_GOOGLE_MAP_ID` build args. Stage `runtime`: Python 3.12 slim, `libodbc2`, `ca-certificates`, `gosu`, user `ridez` (10001), install `requirements.lock`, copy `app`, `migrations`, `wsgi.py`, `gunicorn.conf.py`, `start.sh`, `backup.py`, SPA into `frontend_dist`; `EXPOSE 10000`; `HEALTHCHECK` calls `/api/v1/ready`; `ENTRYPOINT /app/start.sh`, `CMD gunicorn --config gunicorn.conf.py wsgi:app` |
| `.dockerignore` | Excludes `.git`, `node_modules`, venvs, caches, `.env*`, `instance`, `*.db`, `*.key`, `*.pem`, `dist` — keeps secrets and local DBs out of images |
| `.gitignore` | Same idea for Git; keeps `.env.example` |
| `.node-version` / `.python-version` | `22` / `3.12.12` |
| `render.yaml` | Render Blueprint (see [15 — Deployment](15-deployment-and-execution.md)) |
| `requirements.txt` (root) | `-r backend/requirements.lock` for Render Python services that build from the repo root |
| `deploy/start.sh` | Docker entrypoint: as root, `chown` `/var/data` then re-exec as `ridez` via `gosu`; when the command is `gunicorn`, run `flask db upgrade`, optional `bootstrap-admin`, unset `BOOTSTRAP_ADMIN*`, then `exec` |
| `deploy/render-build.sh` | Native Render build: pip install, check npm exists, `npm ci --include=dev`, `npm run build`, copy `frontend/dist` → `backend/frontend_dist` |
| `deploy/render-start.sh` | Native Render start: verify SPA build, `db upgrade`, optional bootstrap, unset bootstrap vars, `exec gunicorn` |
| `deploy/smoke.py` | Container end-to-end smoke test (used in CI) |
| `deploy/backup.py` | `python backup.py <new-file>`: SQLite online backup via `sqlite3.backup`, refuses overwrite, `PRAGMA integrity_check` |
| `.github/workflows/checks.yml` | CI on push to `main` and PRs |
| `README.md` | Setup, run, behaviour notes |
| `TEST_PAYMENTS.md` | Mock QR testing guide |
| `docs/*.md` | Older topic notes: product blueprint, screen flows, sessions, cancellations, driver availability/management, vehicle details, admin monitoring, address search & revenue, Google Maps setup, Render deployment |

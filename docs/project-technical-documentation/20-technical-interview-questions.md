# 20 — Technical interview questions and answers

[← Back to index](README.md) · Next: [21 — Quick revision sheet →](21-quick-revision-sheet.md)

75 questions with answers grounded in this repository. File references let you jump to the code if challenged.

## Architecture

**1. Describe the overall architecture.**
A modular monolith: React 19 SPA → Flask REST API `/api/v1` + Flask-SocketIO in one Python process → SQLAlchemy → SQLite (Render) with SQL Server as an untested target. Layers: route modules (`routes.py`, `ride_routes.py`, `test_payment_routes.py`) → services (`ride_service`, `matching`, `fare_service`, …) → repositories (`ride_repository`, `repositories`) → `models.py`. A 1-second background thread (`realtime.py`) advances matching and dispatches outbox events.

**2. Why a single process?**
The Socket.IO rooms, connection map, rate limiters and trip-map cache are in memory, and the outbox dispatcher emits through the local Socket.IO server. `gunicorn.conf.py` hard-codes `workers = 1` with 100 threads, and `render.yaml` sets one instance. It was a deliberate choice to avoid Redis for local Windows development (README).

**3. How does the frontend get data?**
Mostly from one endpoint, `GET /api/v1/workspace`, which returns a role-specific snapshot built by `ride_service.snapshot`. `useWorkspace` polls it (15 s with a live socket, 2 s without) and refetches whenever a `workspace.changed` event arrives.

**4. Why send "something changed" events instead of the data itself?**
Events are at-least-once and may be missed while disconnected; refetching canonical state makes duplicates and losses harmless and keeps client logic simple. The blueprint states "events are notifications, not the only source of truth".

**5. What is the transactional outbox here?**
`ride_repository.notify()` inserts `outbox_events` rows in the same DB transaction as the business change. `realtime.dispatch()` reads undelivered rows, emits `workspace.changed` to `user:{id}` or `admins`, marks them delivered, and deletes delivered rows older than 7 days.

**6. Where does the background work run and how does it start?**
`realtime.start_worker(app)` → `socketio.start_background_task(loop)`; `loop` calls `tick()` every second. Started by `run.py` (dev) or Gunicorn's `post_worker_init` (prod). `flask run` does not start it.

**7. What happens if the worker thread dies?**
`tick` exceptions are caught and logged generically and the loop continues. If the thread itself stopped, `/ready` turns 503 after 10 s (Render health check), and matching still progresses on requests because `ride_service.expire()` calls `matching.advance()`; only socket pushes would stop (clients fall back to polling).

**8. How is the code organized?**
Flat `backend/app/` with one module per domain; flat `frontend/src/` with one file per component/hook. Tests in `backend/tests/`, migrations in `backend/migrations/versions/`, deployment in `deploy/`.

## Backend

**9. Walk me through `create_app`.**
Loads `backend/.env` without overriding env, decides development vs production, auto-generates dev secrets into `instance/`, sets DB URL/secrets/flags, validates required settings (≥ 32-char distinct secrets in prod, Google key with Google provider), optionally wraps `ProxyFix`, initializes SQLAlchemy/Migrate, imports route modules, registers the blueprint at `/api/v1`, initializes Socket.IO and SPA serving, adds JSON 404/405 and CLI commands.

**10. How does a route enforce roles?**
`@authenticated('driver')` in `routes.py` requires a Bearer token, calls `session_service.authenticate`, stores `g.user`, and returns 403 if the role differs. Ownership is checked again inside services.

**11. Which file controls booking?**
`ride_service.book` (`backend/app/ride_service.py`), exposed by `POST /rides` in `ride_routes.py`.

**12. Which file controls trip state transitions?**
`ride_service.move` with the `transitions` map; writes via `ride_repository.transition`. Route: `POST /rides/<id>/<action>` (`ride_routes.progress`).

**13. Why are some imports inside functions?**
To break circular imports (`ride_service` ↔ `admin_service`/`trip_map_service`, `routes` ↔ `session_service`) and delay heavy imports (Alembic in `/ready`).

**14. How are errors returned?**
Services raise `ApiError(message, status)`; `routes.api_error` returns `{"error": message}` with that status and `no-store`. There's no JSON handler for unexpected exceptions (a known gap).

**15. How is money handled?**
`Decimal` with `ROUND_HALF_UP` to 0.01 (`money()` helpers), stored as `Numeric(10,2)`, sent as strings. Revenue allocation rounds the driver amount and gives the company the remainder so the sum is exact.

**16. How is the fare calculated?**
`fare_service.calculate`: `base + distance_m/1000 × per_km + duration_seconds/60 × per_minute`, then `max(…, minimum)`, then × the highest eligible surge multiplier capped at `max_multiplier`. Defaults: ₹40 + ₹12/km + ₹2/min, minimum ₹40, surge off.

**17. How does surge work?**
Only if `surge_enabled`. Candidates: zones (enabled, scheduled in policy timezone, pickup within radius), traffic (`duration/staticDuration ≥ traffic_threshold`), demand (`requests ≥ demand_min_requests` and `requests/max(1,drivers) ≥ demand_threshold` within 1 km). Highest wins; reasons stored in `surge_reason`, `(capped)` appended if capped.

**18. How do overnight surge zones work?**
`fare_service.scheduled`: if `start > end`, the window belongs to its start day — active on a selected day after `start`, or on the following day before `end`. `start == end` means all day.

**19. What does the simulator do?**
`route_provider.compute` derives a stable distance (2–20 km) from a SHA-256 of the lowercase labels and 3 min/km duration (≥ 5 min). Enabled by `ROUTE_PROVIDER=simulator` and `SIMULATOR_ENABLED=1` (dev defaults).

**20. What is `expire()` and why is it called everywhere?**
`ride_service.expire()` runs `matching.advance()` then `db.session.expire_all()`, so every request first catches up overdue matching deadlines and sees fresh data, even if the worker is lagging.

## APIs

**21. List the main ride endpoints.**
`POST /fares/quotes`, `POST /rides`, `POST /rides/{id}/accept|reject`, `POST /rides/{id}/depart|arrive|start|complete|cancel`, `GET /rides/{id}`, `GET /rides/{id}/map`, `POST /rides/{id}/payment-method|confirm-cash|rating|test-payment`, `GET /workspace`.

**22. How is booking made idempotent?**
`rides.quote_id` is unique. `book()` returns the existing ride if one exists for the quote; on `IntegrityError` from a concurrent duplicate it rolls back and returns the existing ride.

**23. What does `POST /driver/availability` expect?**
`{"available": true, latitude, longitude, accuracy_m, recorded_at}` to go online (fresh fix required) or `{"available": false}`. While on a trip, `available:true` only saves `resume_available`.

**24. What's the difference between `/health` and `/ready`?**
`/health` always 200 with config and worker status. `/ready` returns 200 only if `alembic_version` equals the migration head and the worker ticked in the last 10 s; else 503. Docker and Render use `/ready`.

**25. Why do some endpoints return 404 instead of 403?**
`ride_service.accessible` and payment/rating services return 404 for rides you don't participate in, so the API doesn't reveal that a ride ID exists.

**26. What status codes does the API use for conflicts?**
409 for state conflicts/stale versions/lost races; 410 for expired QR links; 422 for no route / fare too large; 429 for rate limits; 502/503/504 for Google failures.

**27. Is there API documentation?**
`/api/v1/openapi.json` and `/api/v1/docs` (Swagger UI from jsDelivr), built in `spec.py`. It's incomplete (no response schemas, missing test-payment routes); this knowledge base is more complete.

## Database

**28. What are the core tables?**
`users`, `fare_quotes`, `rides`, `active_rides`, `ride_invitations`, `ride_match_rounds`, `driver_presence`, `driver_locations`, `driver_vehicles`, `revenue_ledger`, `revenue_share_settings`, `fare_policies`, `admin_audit`, `auth_sessions`, `refresh_tokens`, `outbox_events`, `ride_payments`, `mock_payments`, `ride_ratings` (19).

**29. How do you guarantee a user has only one active ride?**
`active_rides` has primary key `user_id`. Booking inserts the rider's row, acceptance inserts the driver's; a second insert raises `IntegrityError`. Rows are deleted by `ride_repository.release` on completion, cancellation or NO_DRIVER_FOUND.

**30. How do you prevent inviting the same driver twice?**
`ride_invitations` primary key `(ride_id, driver_id)`, plus `invite()` skips drivers already invited for that ride.

**31. Why is the ride's `expires_at` reused for rounds?**
It is the current round deadline. `advance()` claims a round by matching both `round_no` and `expires_at`, which makes processing idempotent between the worker and requests.

**32. How are migrations handled?**
Alembic via Flask-Migrate, 13 linear revisions (head `c51e8a2f90d4`), run at container start (`deploy/start.sh`). `batch_alter_table` is used for SQLite compatibility. Migration `7ba01cddd40c` back-fills payments for already-completed rides.

**33. Are there seeds?**
No. Defaults are in code (`DEFAULT_POLICY`, 85/15 split); admins are created via CLI or bootstrap env vars.

**34. Which DB constraints enforce business rules?**
CHECKs for ride status, user role/status (suspended only for drivers), revenue split sum = 100, payment status/method/completeness, rating stars 1–5 and role. Unique: mobile, user_code, quote_id; PK-based uniqueness for claims, ledgers, payments, ratings, versions.

**35. What indexes exist and what's missing?**
Present: `driver_locations.updated_at`, `outbox_events.delivered_at`, `revenue_share_settings.effective_from`, `auth_sessions.user_id`, `refresh_tokens.session_id`, `ride_ratings.ratee_id`. Missing: `rides(status, expires_at)`, `rides(rider_id)`, `rides(driver_id)`, `ride_invitations(driver_id)`, `revenue_ledger(driver_id)`.

## Authentication and security

**36. How does authentication work internally?**
Login creates an `auth_sessions` row and a refresh token (hash stored). The response has a 15-min HS256 JWT `{sub, sid, iat, exp}` and sets the `ridez_refresh` HttpOnly cookie. Each request: decode JWT with required claims → load user (not disabled) → check the session row is valid and belongs to the user → role check.

**37. Where is the token stored on the client?**
In a module variable in `authSession.js` (memory only). On reload, `AuthProvider` calls `/auth/refresh` with the cookie.

**38. How does refresh rotation and replay detection work?**
`session_service.refresh` marks the presented token used with `UPDATE … WHERE used_at IS NULL`; if the row count isn't 1, the token was reused and the session is revoked. Otherwise a new token is issued.

**39. How do you protect cookie endpoints from CSRF?**
`check_origin()` requires `X-Session-Request: 1`, a same-host or trusted `Origin`, and rejects `Sec-Fetch-Site: cross-site`. Cookie is `SameSite=Lax` and path-scoped. Business endpoints use Bearer tokens, which browsers don't attach automatically.

**40. How are passwords stored?**
`werkzeug.security.generate_password_hash` (scrypt by default in Werkzeug 3.x). Login uses `check_password_hash` and a dummy hash for unknown users.

**41. What rate limiting exists?**
In-memory sliding windows: 10 login/register attempts per minute per IP, 10 quotes per minute per rider, 5 failed OTPs per minute per driver. Per-process only.

**42. How is admin creation protected?**
Public registration rejects `admin`. Admins come from `flask create-admin` or `flask bootstrap-admin` reading `BOOTSTRAP_ADMIN_*` env vars at startup; the bootstrap never promotes existing users and the env vars are unset before Gunicorn runs.

**43. What privacy rules are enforced?**
Riders never receive `settlement`; driver coordinates are never in admin views (`location_service.public` omits them); trip maps are participant-only; OTP only in the rider's snapshot; rating comments only for admins.

**44. What happens on logout to an active driver?**
`stop_requests`: `available=false`, `resume_available=false`, pending invitations closed, notify. The active trip continues and the driver can still complete it after signing back in.

## Data flow

**45. How does data move from frontend to database when booking?**
`BookingPanel` → `perform('/rides', {quote_id})` → `api()` with Bearer → `ride_routes.book` → `ride_service.book` → inserts `rides`, `active_rides`, `ride_match_rounds`, `ride_invitations`, `outbox_events` → commit → 201 ride JSON → `refresh()` → `/workspace` → `ActiveRidePanel`. Drivers get the socket event and see the invitation.

**46. How does the rider learn a driver accepted?**
Acceptance writes outbox events for the rider; the worker emits `workspace.changed` within ~1 s; `useWorkspace` refetches; `AssignedRideDetails` renders. Without sockets, the 2-second poll catches it.

**47. How does the driver's location reach the rider's map?**
`useDriverLocation` → `PUT /driver/location` → `driver_locations`. The rider's `useTripRoute` polls `GET /rides/{id}/map` every 10 s; `trip_map_service.position` returns fresh coordinates; `GoogleRouteMap` moves the taxi marker.

**48. What happens at completion?**
In one transaction: ride → COMPLETED, `revenue_ledger` insert, `ride_payments` PENDING insert, claims deleted, driver availability decided, outbox events. The rider's `usePaymentPrompt` opens the payment modal.

## Third-party integrations

**49. What Google APIs are used and where?**
Routes API from the server (`route_provider.compute`, server key); Maps JavaScript API and Places API (New) from the browser (`googleMaps.js`, `AddressSearch.jsx`, `GoogleRouteMap.jsx`, browser key).

**50. What happens when Google fails during a quote?**
Specific errors: timeout 504, connection 502, quota 503, denied 502 with an allow-listed reason, no route 422, malformed 502. No simulated fallback in Google mode.

**51. How do you limit Google costs?**
Field masks, `polylineQuality: OVERVIEW`, quote rate limit, trip-map cache (60 s per ride/phase/source/target, shared by both participants, coalesced across threads), and Places session tokens.

**52. Why two Google keys?**
The browser key is public and must be referrer/API-restricted; the server key stays secret on the backend. `.env.example` warns never to put the server key in a `VITE_` variable.

## Error handling and edge cases

**53. What if two drivers accept the same ride simultaneously?**
Both run `ride_repository.assign`, a single conditional UPDATE `WHERE status='SEARCHING' …`. One gets row count 1; the other gets 0 → rollback → 409 "Another driver has already accepted this ride". Tested in `test_rides.py::test_concurrent_acceptance_has_one_winner`.

**54. What if one driver accepts two rides simultaneously?**
Both might pass `assign`, but inserting the second `active_rides` row with the same `user_id` fails → `IntegrityError` → rollback → 409.

**55. What if a rider cancels while a driver accepts?**
Both are conditional updates on `rides.status`; whichever commits first wins. The loser's `transition`/`assign` returns 0 → 409. Tested in `test_cancellation.py::test_cancel_race_has_one_valid_outcome`.

**56. What if cash is confirmed while the QR payment succeeds?**
Both call `payment_service.confirm`, `UPDATE … WHERE status='PENDING'`. First wins; cash confirmation then returns 409 "already paid online", or the mock success just doesn't confirm. (A minor inconsistency can leave the mock row SUCCESS; see [18 B2](18-problems-and-improvements.md#potential-bugs).)

**57. What if the server restarts during a search?**
Deadlines are in `rides.expires_at`. On restart, `advance()` claims overdue rounds and schedules each next deadline from the previous one; expired rounds send no invitations; it stops at the first still-open round or ends in NO_DRIVER_FOUND.

**58. What if the driver's GPS goes stale during a trip?**
The trip continues. The map shows the pickup→destination route without a marker; ETA falls back to the booked estimate; at completion the driver won't be auto-available.

**59. What if a location update arrives out of order?**
Older than the stored `recorded_at` → 409; equal → treated as a replay (no change). Jumps faster than 200 km/h plus accuracies plus 100 m are rejected while tracking is fresh.

**60. What if an admin edits fares while a rider holds a quote?**
The quote keeps its stored totals and `fare_rule_version`; booking uses the quote. New quotes use the new version.

## Deployment

**61. How is it deployed?**
Render Blueprint: one Docker web service, persistent 1 GB disk, SQLite at `/var/data/ridez.db`. `start.sh` fixes disk ownership, drops to user `ridez`, runs `flask db upgrade`, optional bootstrap admin, then Gunicorn. Health check `/api/v1/ready`. Manual deploys.

**62. What does CI do?**
pytest, `npm ci && npm run build`, `docker build`, then `deploy/smoke.py` runs the real image: readiness, bootstrap admin, SPA deep links, register/login, Secure cookie, quote/book/cancel, OTP persistence across restart, refresh, logout revocation.

**63. How do you run it locally?**
Backend: venv, `pip install -r backend/requirements.lock`, `flask --app run db upgrade`, `python run.py` (port 5000). Frontend: `npm ci`, `npm run dev` (5173, proxies `/api` and `/socket.io`).

**64. How are backups done?**
`deploy/backup.py` with SQLite's online backup API and an integrity check; must be copied off the disk for disaster recovery.

## Performance and scalability

**65. What are the performance bottlenecks?**
`/workspace` N+1 queries (up to 100 rides × multiple lookups including two rating aggregates each), polling every 2–15 s; Python haversine over all drivers; missing indexes; outbox write amplification (an admin event for every notify, location updates every 10–30 s); SQLite single writer.

**66. How would you scale this application?**
Move to PostgreSQL/SQL Server with indexes; add Redis as Socket.IO message queue and rate-limit store; run multiple Gunicorn workers/instances; make dispatch use `SKIP LOCKED` or leader election; batch-load in `snapshot`; paginate history; spatial index for drivers; reduce notifications for routine location updates.

**67. Is matching safe if two workers ran it?**
Yes for correctness: `expire_round` and `assign` are compare-and-set. The unsafe parts are notifications (local Socket.IO) and limiters/caches.

## Difficult "why" questions

**68. Why Flask and not FastAPI/Django?**
The blueprint specified a Flask REST API with SQLAlchemy and Alembic. Flask-SocketIO's threading mode lets sockets, SQLAlchemy and `requests` share ordinary blocking code without an async rewrite **(inferred)**.

**69. Why is `lock_active_driver` an UPDATE that sets a column to itself?**
It's a portable row lock: acquiring a write lock on the driver's row (or the whole DB in SQLite) serializes availability, acceptance, suspension and completion for that driver, and the WHERE clause doubles as a status check.

**70. Why is the OTP derived instead of stored?**
No migration needed, stable across restarts, unique per ride, and it can't be read from the DB. The trade-off is that rotating `USER_CODE_SECRET` changes OTPs for unstarted rides.

**71. Why does matching schedule the next deadline from the old deadline, not now?**
So catch-up after downtime replays rounds on the original timeline instead of restarting the clock, and stale rounds are recorded without inviting drivers.

**72. Why keep the access token only in memory?**
XSS can't read it from storage, and the long-lived credential is an HttpOnly cookie. The cost is a refresh call on every page load.

**73. What are the limitations of the current architecture?**
Single process; SQLite; foreground-only browser GPS; mock online payments; no recovery or verification; in-memory limits; heavy polling payload; SQL Server untested.

**74. What would you improve with more time?**
Real payments, mobile verification, password recovery; JSON 500 handler and request IDs; fix limiter thread safety; indexes and snapshot batching; CSP; Redis + server DB for scaling; frontend tests in CI; split `RideWorkspace` into role-specific components.

**75. How do you know it works?**
18 pytest modules cover auth, sessions, rides, matching, cancellation, availability, reviews, vehicles, Google fares (mocked), trip maps, revenue, payments, ratings, OTP, privacy, bootstrap and deployment, including thread-race tests on file-backed SQLite. CI also runs a container smoke test. Not covered: live Google, SQL Server, frontend unit tests. (The suite was not re-run while writing this documentation.)

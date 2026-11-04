# 18 — Problems, limitations and future improvements

[← Back to index](README.md) · Next: [19 — Manager explanation guide →](19-manager-explanation-guide.md)

Every item below was found by reading the code. Severity: **High** (correctness/security risk in realistic use), **Medium** (operational or scaling risk), **Low** (polish/maintainability). No code was changed.

## Incomplete or missing functionality

| # | Problem | Where | Why it matters | Impact | Recommendation |
| --- | --- | --- | --- | --- | --- |
| M1 | No real payment gateway; "online" is a mock QR | `test_payment_routes.py`, `payment_service.choose` (ONLINE requires `TEST_PAYMENTS_ENABLED`) | Production can only take cash | Business blocker | Integrate a gateway (e.g. UPI provider) behind `payment_service.confirm`, with webhooks and idempotency keys |
| M2 | No password reset/account recovery, no profile editing | `main.jsx::Account` text | Locked-out users need manual DB work | Support burden | Add OTP/email-based recovery once mobile verification exists |
| M3 | Mobile numbers are not verified | `services.register` | Anyone can register any number | Fraud/impersonation | SMS verification at registration |
| M4 | `disabled` status has no API/UI | `models.User`, no writer | Admins cannot ban riders | Abuse handling gap | Add admin disable/enable endpoints with audit |
| M5 | No in-progress incident/abort flow | `move` blocks cancel for IN_PROGRESS | A breakdown mid-trip can't be closed except by completing | Wrong charges | Add an incident state with admin resolution |
| M6 | No cancellation fees/no-show policy, refunds, taxes, tips | README "remaining milestones" | Commercial readiness | — | Product decisions + ledger types |
| M7 | Admin cannot list/search all rides with pagination | `/workspace` caps at 100 | Ops visibility | — | `GET /admin/rides?page&status&q` |
| M8 | Browser-only GPS (foreground) | `useDriverLocation` | Drivers go stale when switching apps | Missed matches | Native app or PWA background location |
| M9 | OpenAPI incomplete | `spec.py` | Integrators can't rely on it | — | Generate the spec from code (e.g. apispec/pydantic) and cover all routes/response schemas |

## Potential bugs

| # | Severity | Problem | Where | Failure scenario | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B1 | Medium | In-memory limiter dicts are mutated from up to 100 threads without a lock | `ride_routes.quote` (plain `dict`), `services.verify_trip_otp` (plain `dict`), `routes.limit_auth` | Thread A deletes an empty bucket while thread B is in the `for key in list(buckets): while buckets[key]` loop → `KeyError` → HTML 500 (rare, under concurrency) | Guard with a `threading.Lock`, or move to a shared limiter |
| B2 | Low | Mock QR SUCCESS can coexist with a cash-confirmed payment | `test_payment_routes.simulate_test_payment` | Driver confirms cash between the `confirmed_by_other_method` check and the mock UPDATE → `mock_payments.status=SUCCESS` while `ride_payments.method=CASH`; UI shows both "Simulation successful" and "Paid in cash" | Perform the mock update conditionally on `ride_payments.status='PENDING'` in the same statement/transaction |
| B3 | Low | Clearing a zone latitude/longitude input becomes `0` | `FareSettings.jsx` (`Number(e.target.value)`) | Admin clears a field and saves → zone centred at 0°,0° silently | Keep raw strings and validate before submit |
| B4 | Low | Simulator mode: entering only one destination coordinate sends `0` for the other | `BookingPanel.submit` | Destination saved at lat or lng 0 | Require both or neither |
| B5 | Low | Without Web Locks support, two tabs refreshing at once can self-revoke the session | `authSession.locked` falls back to no lock | User signed out unexpectedly in older browsers | Add a localStorage-based mutex fallback |
| B6 | Low | `signOut(true)` keeps the local session if the pre-refresh fails | `authSession.signOut` | User sees an error but still appears signed in with a dead session | On 401 during sign-out, clear local state anyway |
| B7 | Low | `/health.storage` reports `sql-server` for any non-SQLite URL | `routes.health` | Misleading diagnostics | Report the dialect name |
| B8 | Low | Workspace header always says "Development" | `main.jsx::Workspace` | Confusing in production | Drive from `/health` or a build flag |
| B9 | Low | ETA on `TripStatsCard` uses `generated_at` of a cached route (≤ 60 s old) | `TripStatsCard.liveRoute` | Arrival time can be up to a minute stale | Return cache age or compute from request time |
| B10 | Low | No generic JSON 500 handler | `__init__.py` | Frontend shows "Unable to read the server response" on any crash | Add an `Exception` handler |

## Security

| # | Severity | Issue | Where | Recommendation |
| --- | --- | --- | --- | --- |
| S1 | Medium | Rate limits are per-process and IP-only; reset on restart; no per-account lockout | `routes.limit_auth` etc. | Shared limiter (Redis) keyed by IP **and** mobile; progressive delays |
| S2 | Medium | No Content-Security-Policy | `web.py::security_headers` | Add CSP allowing self + Google Maps domains |
| S3 | Low | Swagger UI loads scripts from jsDelivr without Subresource Integrity, and `/docs`, `/openapi.json`, `/health` are public | `routes.docs`, `routes.health` | Pin with SRI or self-host; restrict docs in production |
| S4 | Low | `JWT_SECRET` also signs mock QR tokens (salted) | `test_payment_routes.signer` | Separate key per purpose |
| S5 | Low | Password policy is length-only (10–128) | `services.register` | Add breached-password check |
| S6 | Low | `pytest` and ODBC libs shipped in runtime image | `Dockerfile`, `requirements.lock` | Split runtime vs dev requirements |
| S7 | Info | Trip OTP is a static per-ride PIN | `services.trip_otp` | Acceptable by design; document rotation impact of `USER_CODE_SECRET` |
| S8 | Info | Mock QR link is a 15-min bearer capability | `test_payment_routes` | Keep feature disabled in production (default) |

## Performance bottlenecks

| # | Issue | Where | Impact | Recommendation |
| --- | --- | --- | --- | --- |
| P1 | N+1 queries in ride serialization | `ride_service.public` (quote, driver, rider, 2× `rating_service.summary`, mock payment, payment, ledger per ride) × up to 100 rides | A single `/workspace` can issue hundreds of queries; polled every 2–15 s per client | Batch-load related rows; cache rating summaries; paginate history |
| P2 | Admin snapshot computes `drivers` (≤ 100 with locations) and drivers compute `allocated_earnings` that the UI never reads | `ride_service.snapshot` | Wasted queries on every admin poll | Remove or move behind explicit endpoints |
| P3 | Haversine filter over all eligible drivers in Python | `matching.invite`, `fare_service.demand_signal` | O(N) per round/quote | Bounding-box prefilter in SQL or a spatial index |
| P4 | Missing indexes: `rides(status, expires_at)`, `rides(rider_id)`, `rides(driver_id)`, `ride_invitations(driver_id, status)`, `revenue_ledger(driver_id)`, `outbox_events(user_id)` | `models.py` | Full scans as data grows (`expired_searches` runs every second) | Add indexes via migration |
| P5 | Every `notify()` adds an admin event; location updates notify every 10–30 s per driver | `ride_repository.notify`, `location_service.update` | Outbox write amplification; admins refetch constantly | Don't notify on routine location updates (only on freshness changes); coalesce admin events |
| P6 | `disconnect_invalid()` runs DB lookups for every socket every second | `realtime.py` | O(connections) queries/s | Check only on expiry time or on revocation events |
| P7 | Unbounded growth: `refresh_tokens`, `auth_sessions`, `fare_quotes`, `ride_match_rounds` | — | DB size | Periodic cleanup job |

## Scalability concerns

- Single process/instance (sockets, limiters, caches in memory) — see [13 §6](13-background-and-realtime-processes.md#6-why-single-process-matters).
- SQLite single-writer; SQL Server path untested and driver not installed.
- Recommendation path: (1) move to PostgreSQL/SQL Server with proper indexes; (2) add Redis as the Socket.IO message queue and rate-limit store; (3) elect one worker instance for `advance()`/`dispatch()` or keep them safe for concurrency (matching already is) and make dispatch use `SELECT … FOR UPDATE SKIP LOCKED`; (4) scale Gunicorn horizontally.

## Code organization and maintainability

| # | Issue | Where | Recommendation |
| --- | --- | --- | --- |
| C1 | Misleading module names: `services.py` = auth/OTP; two repository modules | `backend/app` | Rename to `auth_service.py`, `user_repository.py` |
| C2 | Many function-local imports to avoid cycles | `ride_service`, `routes`, `ride_routes` | Restructure dependencies (e.g. move `accessible` to a shared module) |
| C3 | `spec.py` mutated incrementally | `spec.py` | Declarative spec or generated |
| C4 | Very long single-line JSX and Python lines | `RideWorkspace.jsx`, `main.jsx`, `models.py` | Format with Prettier/Black; split `RideWorkspace` into rider/driver/admin views |
| C5 | Manual validation duplicated (text lengths, versions, reasons) | services | Shared validators or a schema library |
| C6 | No frontend tests in CI; browser script has hard-coded paths | `frontend/tests` | Add Vitest + Playwright in CI |
| C7 | Unused code: `repositories.by_id`, `GET /me`, `/driver/overview`, `/admin/overview`, `GET /rides/{id}` (not used by SPA) | | Keep if intended for API clients; otherwise remove |
| C8 | Duplicate currency formatters across files | `RideWorkspace`, `AssignedRideDetails`, `PaymentStatus`, `TestPayment` | Shared `format.js` |
| C9 | Naive vs aware datetimes mixed (`users.created_at` aware, others naive) | `models.py` | Standardize |

## Database optimization opportunities

1. Indexes listed in P4.
2. Store rating aggregates (average/count) on users or a materialized table updated on insert.
3. Partition/clean outbox and token tables.
4. Use `RETURNING` (where supported) to avoid re-reads after conditional updates.
5. Enable SQLite WAL mode + busy timeout while SQLite remains in use **(recommended; not currently configured)**.

## Priority recommendation list

1. Real payments and mobile verification (business blockers).
2. Fix B1 (limiter locking) and add a JSON 500 handler.
3. Add indexes (P4) and reduce `/workspace` query count (P1, P2).
4. CSP + shared rate limiting (S1, S2).
5. Database migration off SQLite + Redis for multi-instance.

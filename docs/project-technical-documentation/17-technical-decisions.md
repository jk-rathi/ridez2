# 17 — Technical decisions and project design

[← Back to index](README.md) · Next: [18 — Problems and improvements →](18-problems-and-improvements.md)

Each decision is tagged **Documented** (stated in code comments, README or `docs/`) or **Inferred** (my reading of why the code is shaped this way).

## 1. Architecture decisions

| Decision | Rationale | Tag |
| --- | --- | --- |
| Single modular monolith (Flask app serving SPA + API + Socket.IO) | One origin removes CORS and simplifies cookie security; one deployable | Documented (`web.py` docstring "Serve the Vite build from the same origin as HTTP and Socket.IO APIs"; Render guide) |
| Exactly one process | Matching loop, socket dispatcher, limiters and caches are in-process | Documented (`gunicorn.conf.py` comment, README) |
| Flask-SocketIO in **threading** mode, no Redis | Avoid a separate Redis install for local Windows development | Documented (README) |
| Persist matching deadlines and events in the DB | Restarts must recover overdue work; events must not be lost | Documented (README, blueprint) |
| Socket events are invalidations; clients fetch canonical state | Avoid divergent client state; reconnect is trivial | Documented (blueprint: "events are notifications, not the only source of truth") |
| Route-provider interface with deterministic simulator | Develop without Google; never silently substitute simulated data in production | Documented (blueprint) |
| SQL Server as target DB, SQLite in practice | Organizational target (blueprint) vs. single-instance pilot on Render disk | Documented |
| Conditional UPDATEs + uniqueness for concurrency | Portable across SQLite and SQL Server; no `SELECT FOR UPDATE` (unsupported by SQLite) | Inferred (comment on `ActiveRide`: "portable uniqueness guard") |
| No-op UPDATE as a lock | Serialize availability/acceptance/suspension on the same row | Documented (comment "Serialize availability/assignment with suspension using the same user row") |
| Access token in memory + HttpOnly rotating refresh cookie | XSS cannot steal long-lived credentials; reload restores session | Documented (`authSession.js` comment; blueprint) |
| Session row check on every request | Immediate revocation | Inferred |
| Immutable quotes and versioned policies/splits | Later changes must not reprice existing quotes/settlements | Documented (README) |
| Decimal money, strings in JSON | Avoid float accounting errors | Documented (blueprint) |
| Highest multiplier wins, capped (not compounded) | Predictable surge | Documented (UI text, README) |
| Revenue allocation ≠ payment | Accounting entry only; earnings "received" only when payment confirmed | Documented |
| Per-ride HMAC OTP, no DB column | Stable across restarts, unique per ride, no storage | Documented (README) |
| Vehicle snapshot on ride | History/receipts immutable | Documented |
| Trip map geometry cached 60 s, shared by participants | Bound Google billing | Documented (README, spec) |
| Admin cannot self-register | Privilege escalation prevention | Documented |
| Riders never see revenue split | Financial privacy | Documented (`docs/ADMIN_MONITORING.md`, spec) |

## 2. Design patterns used

| Pattern | Where |
| --- | --- |
| Application factory | `create_app` |
| Blueprint + decorator-based auth | `routes.api`, `authenticated(role)` |
| Service layer / repository | `*_service.py`, `ride_repository.py`, `repositories.py` |
| Transactional outbox | `OutboxEvent` + `dispatch()` |
| Optimistic concurrency (version numbers) | fare policy, revenue split, driver status, vehicle |
| Compare-and-set via SQL | `transition`, `assign`, `expire_round`, `confirm` |
| Idempotency keys | `rides.quote_id`; exact-retry detection elsewhere |
| Strategy / adapter | `route_provider.compute` (simulator vs Google) |
| Snapshot / event-sourced history (light) | `fare_quotes.rate_snapshot`, `admin_audit`, `ride_match_rounds` |
| Single-flight / request coalescing | `authSession.refreshSession` (`pendingRefresh`), `trip_map_service.cached_route` (`Future`) |
| Capability URL | Mock QR token |
| Serializer methods on models | `public()` |
| Custom hooks | `useWorkspace`, `useDriverLocation`, `useTripRoute`, `usePaymentPrompt`, `usePaymentConfirmedFlash`, `useTestQr` |

## 3. Code organization

- **Backend:** flat `app/` package, one module per domain area. Route files are thin. Some naming is historical: `services.py` is really "auth/account service", and there are two repository modules (`repositories.py` for users, `ride_repository.py` for everything else).
- **Frontend:** flat `src/` with one file per component/hook, contrary to the blueprint's suggested `features/` folders **(documented plan vs actual)**.
- **Docs:** topic notes per milestone in `docs/`.

## 4. Reusable logic

| Logic | Reused by |
| --- | --- |
| `ride_service.expire()` | quote, book, accept, availability, move, snapshot, details |
| `ride_repository.notify/notify_ride` | every mutating service |
| `location_service.is_fresh/distance_m/coordinate` | matching, fare demand/zones, trip map, completion |
| `route_provider.compute` | quotes, trip map, CLI |
| `session_service.stop_requests` | logout, refresh revoke, admin reviews |
| `ride_service.public` | workspace, booking, accept, move, details |
| Frontend `api`, `perform`, `getPosition`, `GoogleRouteMap` | everywhere |

## 5. Separation of concerns — strengths and leaks

Strengths: route handlers hold no business logic; services own validation and transactions; serializers decide visibility.

Leaks:
- Rate limiting is inline in `ride_routes.quote` and `services.verify_trip_otp` rather than in middleware.
- `test_payment_routes.py` contains business logic (status update, notifications) in the route module.
- `ride_service.public` lazily imports models and reads config, and performs many queries (presentation + data access mixed).
- `spec.py` is mutated incrementally instead of declared once.

## 6. Scalability limitations

| Limitation | Cause |
| --- | --- |
| One process only | In-memory socket rooms, limiters, caches |
| SQLite write serialization | Every location update, outbox write and state change needs the single DB write lock; workspace polls also run `advance()`, which writes whenever rounds or locations are due |
| `/workspace` is query-heavy | Up to 100 rides × ~8–10 queries each (quote, users, two rating aggregates, payments, ledger) per poll; polls every 2–15 s per client |
| Haversine over all eligible drivers in Python | No spatial index; O(drivers) per matching round and per demand calculation |
| `demand_signal` scans all SEARCHING rides | O(open requests) per quote |
| `advance()` runs on most requests | Extra write attempts under load |
| Admin event per notification | Every `notify()` adds an admins event; with many drivers sending locations every 10–30 s, outbox volume grows quickly |
| `dispatch()` 200 events/s cap | Backlog under heavy load |
| `disconnect_invalid()` queries per socket each second | O(connections) DB queries per second |

## 7. Performance considerations already present

- `pool_pre_ping`, indexes on `driver_locations.updated_at`, `outbox_events.delivered_at`, `revenue_share_settings.effective_from`, `auth_sessions.user_id`, `refresh_tokens.session_id`, `ride_ratings.ratee_id`.
- Long-term immutable caching of hashed `assets/*`.
- Trip-map route cache and coalescing.
- Polling slows to 15 s when sockets are live.
- Google field masks and `polylineQuality: OVERVIEW` to reduce payload/cost.
- Debounced address search with session tokens.

## 8. Technical compromises (acknowledged in code/docs)

| Compromise | Source |
| --- | --- |
| In-process rate limiters | "Development limiter only; deploy a shared Redis limiter before multiple workers" (`routes.py`) |
| SQLite in production pilot | Render guide: "suitable for a single-instance pilot" |
| Browser geolocation instead of native tracking | README: "Production background tracking will require a native/mobile implementation" |
| Mock online payments | `TEST_PAYMENTS.md`, `MockPayment` docstring |
| SQL Server not validated | README |
| Legacy compatibility paths | approve without `version`; cancel search without `reason` |

## Documented plans vs actual implementation

| `docs/PRODUCT_BLUEPRINT.md` says | Actual code |
| --- | --- |
| SQL Server via pyodbc | SQLite in all exercised environments |
| Redis-backed background worker | In-process thread, no Redis |
| `frontend/src/{app,components,features,lib,styles}` | Flat `src/` |
| `backend/app/{api,services,repositories,models,schemas,jobs}` | Flat modules, no schemas package |
| Socket events `invitation.created`, `ride.assigned`, `driver.location_changed` with versions | Single `workspace.changed {event_id, server_time}` |
| Routes like `GET /driver/invitations`, `/admin/rides`, `POST /maps/routes` | Replaced by `/workspace` snapshot |
| Driver state enum (OFFLINE, AVAILABLE, …) | Derived from `users.status` + `driver_presence` + `active_rides` + location freshness |
| Event envelopes with entity ID, state version, deadline | Only `event_id` and `server_time` |

# ridez.io product blueprint

Status: initial implementation baseline. The uploaded GenZ@Work guide supplies feature requirements; this document records implementation decisions and open business policies.

## Product and scope

A responsive taxi booking web application with rider, driver, and admin workspaces. Use React with JavaScript, Vite, and React Router. Backend: Flask REST API, SQLAlchemy, Alembic, SQL Server via pyodbc/ODBC Driver 18, Flask-SocketIO, and a Redis-backed background worker. Keep controllers thin; services own business rules and repositories own persistence.

The first usable release covers registration, mobile/password login, a quoted ride, driver matching, the full trip lifecycle, and an auditable earnings allocation. Payment collection, automated transfers, SMS/OTP, native background tracking, and automated refunds are outside this release. A settlement ledger entry means an allocation was recorded, not that money was transferred.

Provisional defaults: INR, Asia/Kolkata for business schedules, UTC for stored timestamps, English UI. These are configurable, not hard-coded into fare calculations. Rates and service-area limits require explicit configuration; never present invented rates as production prices.

## User experiences

- Rider: choose pickup and destination, review an itemized quote, request a ride, see search progress, follow the assigned driver and trip, and review history.
- Driver: register for approval, grant location permission, go available, accept or reject invitations, progress a trip, and review allocated earnings.
- Admin: approve/suspend drivers, monitor rides and location freshness, configure fares/surge, change revenue allocation, and inspect audit history.

Design direction: mobile-first map workspace, clear fare and status cards, large driver action buttons, accessible form labels and focus states, and status text that does not depend on color. Admin pages use desktop-friendly tables with usable mobile alternatives. Confirm destructive actions and provide specific loading, empty, denied, stale, and retry states.

## Technical boundaries

Suggested structure:

```text
frontend/src/{app,components,features,lib,styles}
backend/app/{api,services,repositories,models,schemas,jobs}
backend/migrations/
backend/tests/
docs/
```

Frontend feature folders: auth, rider, driver, admin. Use Fetch through one API client and Socket.IO through one authenticated connection manager. Fetch canonical state on reconnect; events are notifications, not the only source of truth.

Use a route-provider interface with a deterministic development simulator and a Google implementation. Simulator data must be visibly labeled. Production must not silently substitute simulated routes or fares when Google fails. Browser map keys are public but API/referrer restricted; server keys remain server-side. Google credentials and SQL Server access are prerequisites for live integration validation.

Authentication uses normalized E.164 mobile numbers and securely hashed passwords, without OTP. A mobile number is not verified ownership merely because it was registered. Use short-lived access tokens in memory and rotating refresh tokens in secure HttpOnly cookies, with origin/CSRF protection on cookie-authenticated mutations. Rate-limit login, normalize errors, reject disabled accounts, and enforce roles on HTTP and socket access. Public registration cannot create admins; initial admin provisioning uses a protected backend command. Driver activation requires admin approval. Account recovery policy remains a launch prerequisite.

Generate permanent RID-/DRV- account codes once using server-secret HMAC, resolve collisions, and persist unique values. Codes are identifiers, never authentication credentials.

## Core records and invariants

| Records | Key constraints |
| --- | --- |
| Users, drivers | Unique normalized mobile and permanent code; approved drivers only |
| Driver locations | One latest location per driver; server receipt and capture timestamps |
| Rides | At most one active ride per rider and driver |
| Match rounds, invitations | Unique round per ride; deduplicated driver invitations; server deadlines |
| Fare rules, zones, quotes | Decimal money; currency; versioned rule references and immutable quote components |
| Revenue settings, ledger | Effective dates; percentages total 100; one settlement per ride |
| Admin audit log | Actor, action, reason, before/after, timestamp |
| Refresh sessions, outbox | Revocable sessions; transactionally recorded events for reliable delivery |

Use SQL Server-compatible migrations and integration tests. SQLite is not sufficient evidence for SQL Server locking or concurrent acceptance.

## Ride and driver rules

Ride states: SEARCHING → ASSIGNED → ARRIVING → WAITING → IN_PROGRESS → COMPLETED. SEARCHING may terminate as CANCELLED or NO_DRIVER_FOUND; ASSIGNED, ARRIVING and WAITING may terminate as CANCELLED by the rider or assigned driver with a recorded reason. Pre-trip cancellation must be server-authorized and resolve invitations/driver state. Mid-trip interruption is an incident workflow, not an unrestricted cancellation button.

Driver states: OFFLINE → AVAILABLE → RIDE_REQUESTED → RIDE_ACCEPTED → ARRIVING_AT_PICKUP → WAITING_FOR_RIDER → ONGOING_RIDE → RIDE_COMPLETED → AVAILABLE/OFFLINE. Include TEMPORARILY_UNAVAILABLE and SUSPENDED with explicit transition guards. Pending invitations are separate records; ending one invitation must not make a driver available while another active assignment exists.

- Send location immediately on availability and target updates every 30 seconds while available and every 10 seconds during an assigned trip. Exclude locations older than 90 seconds. Validate identity, coordinate range, timestamp, accuracy, and implausible movement. Stop collection when offline or permission is withdrawn.
- Start matching at 500 m, expire each round after 30 seconds, and expand by 500 m. Provisional development limit: 5 km / ten rounds; configure before launch. Do not repeatedly invite the same driver for one ride.
- Accept only a current, unexpired invitation. Conditionally assign both ride and driver in one transaction; exactly one competing acceptance succeeds. Concurrent rides competing for the same driver must also have exactly one winner.
- Persist deadlines and jobs so worker restarts recover overdue work. Workers must be idempotent. Persist outgoing events transactionally and retry delivery; clients deduplicate events and resync after reconnect.
- Validate quote ownership, expiry, and route before booking. Lock the confirmed quote. Money uses Decimal with currency-aware rounding; avoid floating-point accounting.
- Surge uses the highest eligible multiplier capped by configuration, with an explicit reason. Missing traffic must follow a documented fallback policy.
- Completion atomically records ride completion, driver state, and settlement. Snapshot the effective revenue split at completion, initially 85/15. Repeated completion returns the existing result. Round driver allocation once and compute company allocation as the remainder.

## API baseline

Prefix: `/api/v1`. Document schemas, roles, success responses, and structured errors in OpenAPI. Mutation retries use idempotency keys for booking and other applicable operations.

| Area | Routes |
| --- | --- |
| Auth | POST /auth/register, /auth/login, /auth/refresh, /auth/logout; GET /me |
| Driver | PUT /driver/location; POST /driver/status; GET /driver/invitations, /driver/earnings |
| Quotes | POST /fares/quotes; POST /maps/routes |
| Rides | POST /rides; GET /rides, /rides/{id}; POST /rides/{id}/accept, /reject, /cancel, /arrive, /start, /complete |
| Admin | GET /admin/drivers, /admin/rides, /admin/audit; protected driver approval/suspension; fare-rule and surge-zone CRUD; GET/PUT /admin/revenue-share |

Socket events: invitation.created/expired, ride.assigned/cancelled/status_changed, driver.location_changed. Authorize room membership by user and ride access. Event envelopes include event ID, entity ID, state version, server timestamp, and deadline where applicable. Limit location visibility to authorized participants and admins.

## Delivery gates

1. Foundation: runnable React JS/Flask projects, SQL Server migrations, auth, roles, permanent codes, OpenAPI; test duplicate mobiles, invalid tokens, disabled users, and role escalation.
2. Vertical slice: visibly simulated route, quote, booking, driver acceptance, lifecycle, settlement, and role-specific screens; verify one end-to-end ride.
3. Presence and matching: persistent rounds/jobs, stale exclusion, realtime recovery; test competing acceptance, competing rides, exact expiry boundary, cancellation races, and worker restart.
4. Live maps and fares: restricted Google keys, real route validation, surge schedules/caps, immutable quotes; test provider failure, timezone boundaries, and monetary rounding.
5. Administration: approval, monitoring, fare/surge edits, revenue rules, audit views; test invalid totals, historical allocations, and repeat completion.
6. Deployment: HTTPS, secrets, migrations, backups/restore, health checks, logs without credentials, retention, and load/concurrency checks. Report simulator and live-provider results separately.

## Business decisions required before launch

Service area; fare/minimum rates; cancellation/no-show policy; taxes, tips, discounts and fees in the eligible fare; account recovery; driver verification; incident support; location retention; production hosting and SQL Server licensing; Google billing/quotas and restricted keys. These do not block building the foundation or labeled simulator. They must not be silently inferred as approved commercial policy.

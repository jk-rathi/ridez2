# 06 — API documentation

[← Back to index](README.md) · Next: [07 — Database documentation →](07-database-documentation.md)

Every endpoint below was read from `backend/app/routes.py`, `backend/app/ride_routes.py` and `backend/app/test_payment_routes.py`. Base URL: `/api/v1`. There are **39 route handlers**; `POST /rides/{ride_id}/{action}` serves five actions, giving 43 logical operations. Two non-API routes in `web.py` serve the SPA.

## Conventions

| Topic | Rule (source) |
| --- | --- |
| Content type | Requests with a body must be a JSON **object**; otherwise 400 `A JSON object is required` (`routes.body`) |
| Auth header | `Authorization: Bearer <access_token>` for protected endpoints (`routes.authenticated`) |
| Error body | `{"error": "<message>"}` (`routes.api_error`) |
| Caching | Every API response carries `Cache-Control: no-store` |
| Money | Decimal strings with 2 dp, currency `INR` |
| Timestamps | ISO-8601 UTC with `Z` (e.g. `2026-11-02T09:15:00.123456Z`); `expires_at` in auth payloads is a Unix integer |
| Not found vs forbidden | Resources you don't participate in return **404**, not 403 |

Common auth errors for every protected endpoint: **401** `Please sign in again` (missing/invalid/expired token, revoked session, disabled user); **403** `You do not have access to this workspace` (wrong role).

### Shared response objects

**User** (`User.public()`):

```json
{"id": 7, "name": "Asha", "mobile": "+919876543210", "user_code": "DRV-ABCDEFGHIJKL",
 "role": "driver", "status": "active", "status_revision": 1,
 "vehicle": {"registration": "MH 12 AB 1234", "model": "Maruti Suzuki Dzire", "color": "White", "version": 1}}
```
`vehicle` appears only for drivers (`null` if none recorded).

**Quote** (`FareQuote.public()`), example from the simulator with default rates:

```json
{"id": "3f2c…-uuid", "pickup": "City centre", "destination": "Riverside",
 "pickup_lat": 19.076, "pickup_lng": 72.8777, "destination_lat": null, "destination_lng": null,
 "distance_km": "17.34", "distance_m": 17340, "duration_min": 52, "duration_seconds": 3120,
 "traffic_available": false, "base": "40.00", "distance_fare": "208.08", "time_fare": "104.00",
 "minimum_adjustment": "0.00", "subtotal": "352.08", "surge_multiplier": "1.00", "surge_amount": "0.00",
 "surge_reason": "No surge", "fare_rule_version": 0, "total": "352.08", "currency": "INR",
 "provider": "simulator", "expires_at": "2026-11-02T09:20:00.000000Z"}
```

**Ride** (`ride_service.public(ride, user)`):

```json
{"id": "9b1e…-uuid", "status": "ASSIGNED", "round_no": 1, "radius_m": 500,
 "quote": { …Quote… },
 "requested_at": "…Z", "expires_at": "…Z", "completed_at": null,
 "driver": {"name": "Ravi", "user_code": "DRV-…", "vehicle": {"registration": "MH 12 AB 1234", "model": "Dzire", "color": "White"},
            "rating": {"average": "4.8", "count": 12}},
 "rider": {"name": "Asha", "rating": {"average": null, "count": 0}},
 "test_payment": null, "payment": null, "test_payments_enabled": true, "cancellation": null}
```

Role-dependent keys:
- `my_rating` — rider/driver viewers, COMPLETED rides only (`null` if not rated yet).
- `ratings` — admins only: list of both ratings with comments.
- `settlement` — drivers and admins only (never riders, never in invitation cards): `{eligible_fare, driver_pct, company_pct, driver_amount, company_amount, currency, status:"ALLOCATED", ride_id, share_version, created_at}`.
- `cancellation` — for CANCELLED rides: `{by: "rider"|"driver"|null, by_you, reason, cancelled_at}`.
- `payment` — `{method, status, amount, currency, confirmed_at}` after completion.
- `test_payment` — `{status, amount, currency, test_only: true}` if a mock record exists.

**Payment** (`RidePayment.public()`): `{"method": "CASH", "status": "CONFIRMED", "amount": "352.08", "currency": "INR", "confirmed_at": "…Z"}`

---

## 1. System endpoints

### `GET /health`
- **File/handler:** `routes.py::health`. **Auth:** none.
- **Response 200:**
```json
{"status": "ok", "stage": "location-matching", "routing_diagnostics_version": 1, "route_provider": "simulator",
 "matching_worker": true, "simulator": true, "storage": "sqlite-development"}
```
`matching_worker` is true if the background loop ticked within 10 s. `storage` is `sqlite-development` for any SQLite URL (including production SQLite) and `sql-server` otherwise.
- **Frontend usage:** none (operational).

### `GET /ready`
- **Handler:** `routes.py::readiness`. **Auth:** none.
- **Logic:** compute Alembic head from `migrations/` (cached in `extensions['migration_head']`), read `alembic_version`, require exact match and a worker tick within 10 s. Any exception → rollback, not ready.
- **200:** `{"status":"ready","database":true,"matching_worker":true}` · **503:** `{"status":"not_ready","database":false,"matching_worker":true}`
- **Used by:** Docker `HEALTHCHECK`, Render `healthCheckPath`, `deploy/smoke.py`.

### `GET /openapi.json` · `GET /docs`
- `spec.SPEC` as JSON; Swagger UI HTML loading `swagger-ui-dist@5` from jsDelivr. **Auth:** none. Partial coverage (see [02](02-folder-and-file-structure.md#backendappspecpy--openapi-303-document)).

---

## 2. Authentication endpoints

### `POST /auth/register`
| Item | Value |
| --- | --- |
| Handler | `routes.py::registration` → `services.register` |
| Middleware | `limit_auth` (10 POSTs/min/IP to login+register combined per IP key) |
| Auth | none |
| Body | `name` (1–100), `mobile` (with country code, ≤ 40 chars), `password` (10–128), `role` (`rider` default, or `driver`) |
| DB | `SELECT users WHERE mobile`; `SELECT users.id WHERE user_code` (loop); `INSERT users` |
| Success | **201** `{"user": User}`; drivers get `status: "pending"` |
| Errors | 400 name/password/role/mobile validation messages; 409 `An account with this mobile already exists` / `Account already exists; please sign in`; 429 `Too many attempts. Try again in one minute` |
| Frontend | `main.jsx::AuthPage.submit` |

Request: `{"name":"Asha","mobile":"+91 98765 43210","password":"correct-horse-battery","role":"rider"}` → mobile stored as `+919876543210`.

### `POST /auth/login`
| Item | Value |
| --- | --- |
| Handler | `routes.py::sign_in` → `session_service.check_origin(require_header=False)` → `services.login` → `session_service.issue` → `cookie()` |
| Headers | `Content-Type: application/json`; the SPA also sends `X-Session-Request: 1` (not required here); `Origin` must be same-host or trusted if present; `Sec-Fetch-Site: cross-site` rejected |
| Body | `mobile`, `password` |
| DB | `SELECT users`; `INSERT auth_sessions`, `INSERT refresh_tokens` |
| Success | **200** `{"access_token":"<JWT>","expires_in":900,"expires_at":1793603700,"user":User}` + `Set-Cookie: ridez_refresh=…; HttpOnly; Path=/api/v1/auth; SameSite=Lax; Max-Age=2592000[; Secure]` |
| Errors | 401 `Mobile or password is incorrect` (unknown, wrong, malformed, disabled); 403 origin errors; 429 rate limit |
| Frontend | `authSession.signIn` |

Pending and suspended drivers **can** log in.

### `POST /auth/refresh`
| Item | Value |
| --- | --- |
| Handler | `routes.py::refresh_session` → `check_origin()` → `session_service.refresh` |
| Headers | **`X-Session-Request: 1` required**; cookie `ridez_refresh` |
| Body | ignored (SPA sends `{}`) |
| DB | `refresh_tokens` lookup; conditional `UPDATE used_at`; `INSERT refresh_tokens`; on failure `UPDATE auth_sessions.revoked_at`, presence/invitation updates for drivers |
| Success | 200 same shape as login + new cookie |
| Errors | 403 `Session request header is required` / `Request origin is not allowed` / `Cross-site session requests are not allowed`; 401 `Please sign in again` or `Session credential was already used. Please sign in again` (both **clear the cookie**) |
| Frontend | `authSession.refreshSession` (boot, timer, 401 retry) |

### `POST /auth/logout`
- **Handler:** `logout_session` → `check_origin()` → `session_service.logout()`. **Headers:** `X-Session-Request: 1`; cookie and/or `Authorization` (fallback if the cookie is missing).
- **Effect:** revoke the matching session, stop driver requests, disconnect revoked sockets. Active rides are preserved.
- **200:** `{"status":"signed_out"}` + cookie deleted. Never fails because of a missing session.

### `POST /auth/logout-all`
- **Handler:** `logout_all_sessions` (`@authenticated()`), `check_origin()`, `logout(g.user, all_devices=True)`.
- **200:** `{"status":"signed_out_all_devices"}` + cookie deleted. **401** also clears the cookie.

### `GET /me`
- `@authenticated()` → `{"user": User}`. Not used by the SPA (it uses the `user` in auth payloads and `/workspace`).

---

## 3. Workspace and rides

### `GET /workspace`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::workspace` → `ride_service.snapshot(g.user)` |
| Auth | any role |
| Side effect | runs `matching.advance()` (may commit round expiries) |
| Success | 200 role-specific snapshot (see [05 §5](05-backend-documentation.md#snapshotuser--the-workspace-payload)) |
| Frontend | `RideWorkspace.jsx::useWorkspace` (poll 2 s/15 s + on socket events) |

Rider example (abridged):

```json
{"rides": [ …Ride… ], "active_ride": { …Ride… }, "simulator": true, "route_provider": "simulator",
 "booking_enabled": true, "user": { …User… }, "recent_cancellation": null,
 "my_rating_summary": {"average": "4.9", "count": 8},
 "rating_tags": ["Great driving","Clean car","Friendly","On time","Smooth ride","Unsafe driving","Late","Rude","Dirty car","Wrong route"],
 "trip_otp": "042917"}
```

Driver adds: `location {fresh, recorded_at, accuracy_m}`, `available`, `resume_available`, `invitations [Ride…]`, `earnings [ledger + payment]`, `allocated_earnings`, `confirmed_earnings`, `pending_earnings`, and `suspension {reason, created_at}` when suspended. Admin adds `metrics` and `drivers`.

### `POST /fares/quotes`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::quote` → `ride_service.quote` |
| Auth | rider |
| Middleware | inline limiter: 10 requests / 60 s per rider (`extensions['quote_attempts']`) |
| Body | `pickup` (1–160), `destination` (1–160), `pickup_lat` (−90..90), `pickup_lng` (−180..180), optional `destination_lat`, `destination_lng` (**required in Google mode**) |
| External | Google Routes `computeRoutes` in Google mode |
| DB | reads `fare_policies`, (demand surge) `rides`/`fare_quotes`/`driver_presence`/`driver_locations`; `INSERT fare_quotes` |
| Success | **201** `{"quote": Quote + "polyline": "<encoded> or null"}` |
| Errors | 400 validation (`Pickup must contain 1–160 characters`, `Pickup latitude must be a finite number between -90 and 90`, `Pickup and destination must be different`, `Select destination coordinates on the map or enter them manually`, `Pickup and destination coordinates must be different`); 422 `No driving route was found between these locations`, `Fare exceeds the supported maximum…`; 429 `Too many fare requests…`; 502 Google denied/invalid/failed; 503 simulator disabled, Google key missing, Google quota; 504 Google timeout |
| Frontend | `BookingPanel.submit` via `perform` |

Request (Google mode):
```json
{"pickup":"Bandra Kurla Complex, Mumbai","destination":"Chhatrapati Shivaji Maharaj International Airport",
 "pickup_lat":19.0662,"pickup_lng":72.8679,"destination_lat":19.0896,"destination_lng":72.8656}
```

### `POST /rides`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::book` → `ride_service.book` |
| Auth | rider |
| Body | `{"quote_id": "<uuid>"}` — the **idempotency key** |
| DB | `fare_quotes`, `rides` (insert SEARCHING), `active_rides` (insert rider), `ride_match_rounds`, `ride_invitations`, `users` (lock), `outbox_events` |
| Success | **201** `{"ride": Ride}`; a retry with the same quote returns the same ride (still 201) |
| Errors | 400 `A quote_id is required`; 404 `Quote not found`; 409 `Quote expired. Request a new estimate`, `Route mode changed. Get a new quote before booking`, `Get a new quote with pickup coordinates`, `You already have an active ride`; 503 simulator disabled |
| Frontend | `BookingPanel` "Confirm ride" |

### `GET /rides/{ride_id}`
- `ride_routes.py::details`; any authenticated user; `expire()`, `accessible()` (participant or admin, else 404), returns `{"ride": Ride}`. Not used by the SPA.

### `POST /rides/{ride_id}/accept`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::accept` → `ride_service.accept` |
| Auth | driver |
| Body | none |
| DB | lock `users`; conditional `UPDATE rides` (assign + vehicle snapshot); `INSERT active_rides`; `UPDATE ride_invitations`; `driver_presence`; `ride_match_rounds.outcome`; outbox |
| Success | 200 `{"ride": Ride}` (status ASSIGNED); idempotent if already this driver's ride |
| Errors | 404 `Invitation not found`; 409 `You already have an active trip`, `Refresh your location before accepting`, `This invitation is no longer available`, `Another driver has already accepted this ride`, `Driver or ride was assigned elsewhere. Refresh and retry`; 403 `You must be approved and available to accept`, `Your driver status changed. New rides are blocked`; 503 simulator disabled |
| Frontend | invitation card "Accept ride" in `RideWorkspace` |

### `POST /rides/{ride_id}/reject`
- Driver. `ride_service.reject`: invitation must exist (404). PENDING → REJECTED + notify. Returns `{"status": "REJECTED"}` (or the current status if not pending).

### `POST /rides/{ride_id}/{action}` — `depart`, `arrive`, `start`, `complete`, `cancel`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::progress` → `ride_service.move` |
| Auth | any authenticated; service enforces: transitions = assigned **driver** only (403 `Only the assigned driver can progress this trip`); cancel = ride's rider or assigned driver (403 `Only the rider or assigned driver can cancel this ride`) |
| Body | `start`: `{"otp":"123456"}` (required JSON object); `cancel`: `{"reason":"Plans changed"}` (optional only while SEARCHING); others: ignored |
| Success | 200 `{"ride": Ride}`; retries of an already-applied transition return the current ride |
| Errors | 404 `Ride not found`, `Unknown trip action`; 409 `Cannot depart a trip in searching state` (etc.), `Ride changed. Refresh and retry`, `Only rides that have not started can be cancelled`, `Ride changed. Refresh and review before cancelling`; 400 `Enter the correct six-digit OTP provided by the rider`, `Reason must contain 1–300 characters`; 429 `Too many OTP attempts. Try again in one minute` |
| `complete` side effects | `revenue_ledger` insert, `ride_payments` PENDING insert, claims released, driver availability decided |
| Frontend | `RideCard` primary button, `CancelRideControl` |

### `GET /rides/{ride_id}/map`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::trip_map` → `trip_map_service.trip_map` |
| Auth | rider or driver participant (admins → 403 `Trip maps are available to the rider and assigned driver only`) |
| External | Google Routes (cached 60 s per ride/phase/source/target) |
| Success | 200 `{"map": {...}}` |
| Errors | 404 not a participant; 409 `Live trip maps are only available for active rides`, `Google road routes are unavailable for simulated rides`, `This ride does not have Google route coordinates`, `Ride state changed. Refresh the trip map`, `Driver location availability changed. Refresh the trip map`; 503 `Google trip routing is currently unavailable`; 429 `Route updates are busy…`; 502/503/504 Google errors |
| Frontend | `TripRouteMap.jsx::useTripRoute` |

Response example:
```json
{"map": {"provider":"google","ride_id":"…","phase":"approach","pickup":{"lat":19.0662,"lng":72.8679},
 "destination":{"lat":19.0896,"lng":72.8656},
 "driver_position":{"lat":19.0601,"lng":72.8611,"recorded_at":"…Z","accuracy_m":12.0},
 "origin_source":"driver","target":"pickup","generated_at":"…Z","refresh_after_seconds":10,
 "polyline":"a~l~Fjk~uO…","distance_m":1200,"duration_seconds":240,"at_destination":false}}
```

---

## 4. Driver endpoints

### `POST /driver/availability`
| Item | Value |
| --- | --- |
| Handler | `ride_routes.py::availability` → `ride_service.availability` |
| Auth | driver |
| Body | `{"available": true, "latitude": 19.076, "longitude": 72.8777, "accuracy_m": 12.5, "recorded_at": "2026-11-02T09:15:00.000Z"}` or `{"available": false}` |
| Success | 200 `{"available": true, "resume_available": true, "active_trip": false}` |
| Errors | 400 `Available must be true or false` + location validation messages; 403 `Your driver status does not allow new requests`, `Driver approval is required`; 409 `Availability changed concurrently. Refresh and retry`, `Location is older than the latest accepted update`, `Location movement is implausible`; 503 simulator disabled (going online only) |
| Frontend | `RideWorkspace.changeDriverAvailability`, `useDriverLocation.pauseRequests` |

### `PUT /driver/location`
- **Handler:** `ride_routes.py::location` → `location_service.update` + commit. **Auth:** driver.
- **Body:** `latitude`, `longitude`, `accuracy_m` (0–200), `recorded_at` (ISO with timezone, ≤ 15 s in future, newer than 90 s ago).
- **200:** `{"location": {"fresh": true, "recorded_at": "…Z", "accuracy_m": 12.5}}` (never echoes coordinates).
- **Errors:** 400 validation / `Location time is stale or in the future`; 403 `Driver approval is required`; 409 `Location updates are only allowed while available or on a trip`, older/implausible.
- **Frontend:** `useDriverLocation.send` every 30 s (10 s on trip).

### `GET /driver/overview`
- Driver. Returns `{approval, trips, allocated_earnings, availability_enabled, available}`. Not used by the SPA.

---

## 5. Payments and ratings

### `POST /rides/{ride_id}/payment-method`
- **Handler:** `payment_method` → `payment_service.choose`. **Auth:** rider (owner, else 404).
- **Body:** `{"method": "CASH" | "ONLINE"}`.
- **200:** `{"payment": Payment}`.
- **Errors:** 400 `Choose CASH or ONLINE`; 404 `Ride not found`; 409 `Payment is only available for completed rides`, `Online payment is not available. Please pay by cash` (test payments disabled), `This ride is already paid`.
- **Frontend:** `PaymentPrompt.choose`.

### `POST /rides/{ride_id}/confirm-cash`
- **Handler:** `confirm_cash` → `payment_service.confirm_cash`. **Auth:** driver (assigned, else 404). **Body:** none (the SPA sends `{}`).
- **200:** `{"payment": {"method":"CASH","status":"CONFIRMED",…}}` (idempotent).
- **Errors:** 409 `Payment is only available for completed rides`, `The rider has already paid online`.
- **Frontend:** `DriverCollectCard.received`.

### `POST /rides/{ride_id}/test-payment`
- **Handler:** `test_payment_routes.py::create_test_payment`. **Auth:** rider (owner).
- **Preconditions:** `TEST_PAYMENTS_ENABLED` (else **404** `Test payments are disabled`), ride COMPLETED (409), not already paid by cash (409 `This ride is already paid`).
- **200:** `{"payment": {"status":"PENDING","amount":"352.08","currency":"INR","test_only":true}, "path": "/test-payment/<signed-token>", "expires_in": 900}`.
- **Frontend:** `TestPayment.jsx::useTestQr.generate`.

### `GET /test-payments/{token}` · `POST /test-payments/{token}`
- **Handlers:** `view_test_payment`, `simulate_test_payment`. **Auth:** none — the signed token is the credential (15 min).
- **POST body:** `{"status": "SUCCESS" | "FAILED" | "PENDING"}`.
- **Logic:** `UPDATE mock_payments SET status WHERE ride_id AND status != 'SUCCESS' AND status != new`; if changed to SUCCESS → `payment_service.confirm(ride,'ONLINE')`; notify rider and driver.
- **200:** `{"payment": {...}}`. **Errors:** 404 disabled/not found; 410 `Test QR expired or invalid…`; 400 `Choose PENDING, FAILED or SUCCESS`; 409 `This ride is already paid in cash`.
- **Frontend:** `TestPaymentPage`.

### `POST /rides/{ride_id}/rating`
- **Handler:** `rate` → `rating_service.submit`. **Auth:** rider or driver (admin → 403 `Only the rider and driver of a trip can rate it`).
- **Body:** `{"stars": 5, "tags": ["Great driving","On time"], "comment": "Smooth ride"}`.
- **200:** `{"rating": {"rater_role":"rider","stars":5,"tags":["Great driving","On time"],"created_at":"…Z","comment":"Smooth ride"}}`.
- **Errors:** 404 `Ride not found`; 409 `You can rate a trip once it is completed`, `You have already rated this trip`; 400 `Choose a rating from 1 to 5 stars`, `Choose up to five of the listed tags`, `Comment must be text of at most 300 characters`.
- **Frontend:** `Rating.jsx::RatingForm.submit`.

---

## 6. Admin endpoints (all require role `admin`)

### `GET /admin/overview`
Full admin `snapshot()` (same as `/workspace` for admins). Not used by the SPA.

### `GET /admin/drivers?page=1&status=&q=`
- **Handler:** `admin_drivers` → `admin_service.driver_list`.
- **Query:** `page` 1–100000, `status` ∈ `''|pending|active|suspended|disabled`, `q` ≤ 100 chars (literal ILIKE over name, user_code, mobile).
- **200:** `{"page":1,"page_size":20,"total":42,"items":[User + {"location":{fresh,recorded_at,accuracy_m},"active_ride":{"id","status"}|null,"rating":{average,count}}]}`.
- **Errors:** 400 `Page must be a positive integer`, `Choose a valid driver status`, `Search must contain at most 100 characters`.

### `POST /admin/drivers/{driver_id}/approve` · `/suspend` · `/reinstate`
- **Handlers:** `approve` (via `ride_service.approve`), `suspend_driver`, `reinstate_driver` → `admin_service.change_driver_status`.
- **Body:** `{"version": <status_revision>, "reason": "Documents verified"}` (`version` optional for approve — legacy clients).
- **Transitions:** approve pending→active, suspend active→suspended, reinstate suspended→active. Each also stops new requests (driver left offline).
- **200:** `{"user": User}`; exact retries are idempotent.
- **Errors:** 404 `Driver not found`; 400 `Reason must contain 1–300 characters`, `A valid driver status version is required`; 409 `Driver status changed. Reload drivers and review again`, `Cannot suspend a pending driver`.
- **Frontend:** `DriverManagement.save`.

### `PUT /admin/drivers/{driver_id}/vehicle`
- **Handler:** `update_driver_vehicle` → `admin_service.save_driver_vehicle`.
- **Body:** `{"version":0,"registration":"mh 12 ab 1234","model":"Dzire","color":"White","reason":"RC verified"}` (registration upper-cased and whitespace-collapsed).
- **200:** `{"user": User}` with updated `vehicle`.
- **Errors:** 404; 400 `A valid vehicle version is required`, `Car number must contain 4–20 letters, numbers, spaces or hyphens`, field length messages; 409 `Disabled driver accounts require a separate review`, `Vehicle details cannot change during an active trip`, `Vehicle details changed. Reload drivers and review again`.
- **Frontend:** `VehicleEditor.save`.

### `GET /admin/fare-settings` · `PUT /admin/fare-settings`
- **Handlers:** `fare_settings`, `update_fare_settings` → `fare_service.settings` / `save`.
- **GET 200:** `{"version": 3, "policy": {...}, "history": [{"version":3,"reason":"…","updated_by":1,"created_at":"…Z"}, …]}`.
- **PUT body:**
```json
{"version": 3, "reason": "Weekend airport surge",
 "policy": {"base":"40.00","per_km":"12.00","per_minute":"2.00","minimum":"40.00","timezone":"Asia/Kolkata",
  "surge_enabled":true,"max_multiplier":"2.00","traffic_enabled":false,"traffic_threshold":"1.25","traffic_multiplier":"1.25",
  "demand_enabled":false,"demand_threshold":"2.00","demand_multiplier":"1.25","demand_min_requests":5,
  "zones":[{"id":"airport","name":"Airport","latitude":19.0896,"longitude":72.8656,"radius_m":2000,"multiplier":"1.50",
            "days":[4,5,6],"start":"18:00","end":"02:00","enabled":true}]}}
```
- **PUT 200:** same as GET. **Errors:** 409 `Fare settings changed. Reload before saving` (stale version or concurrent save); 400 specific validation messages (e.g. `base must be between 0 and 100000, with at most two decimals`, `Enter a valid IANA timezone…`, `Use at most 20 surge zones`, `Zone times must use HH:MM (24-hour format)`).

### `GET /admin/revenue-share` · `PUT /admin/revenue-share`
- **GET 200:** `{"version":2,"active":{…split…},"upcoming":[…],"history":[…],"server_time":"…Z"}`; default active `{"version":0,"driver_pct":"85.00","company_pct":"15.00","effective_from":null}`.
- **PUT body:** `{"version":2,"driver_pct":"80.00","company_pct":"20.00","effective_from":"2026-12-01T00:00:00Z","reason":"New contract"}` (`effective_from: null` = immediately).
- **Errors:** 409 `Revenue settings changed. Reload before saving`; 400 `Percentages must be between 0 and 100 with at most two decimals`, `Driver and company percentages must total exactly 100`, `Effective date must include a timezone, or use null for immediately`, `Scheduled changes must be in the future and within one year`, reason length.

### `GET /admin/audit?page=1&category=&q=`
- **Handler:** `admin_audit` → `admin_service.audit`. `category` ∈ `''|driver|fares|revenue`.
- **200:** `{"page":1,"page_size":20,"total":5,"items":[{"id":"…","category":"driver","action":"driver.suspended","actor_id":1,"actor_name":"Admin","created_at":"…Z","reason":"…","target":"7"}]}`.

### `GET /admin/audit/{category}/{identifier}`
- `identifier` is an `admin_audit` UUID for `driver`, or a version integer for `fares`/`revenue`. Invalid → 404 `Audit entry not found`.
- **200:** `{"title":"Driver suspension","subject":"Ravi · DRV-…","changes":[{"field":"Account status","before":"Active","after":"Suspended"}]}`; revenue adds `effective_from`.

---

## 7. Non-API routes (`web.py`)

| Route | Behaviour |
| --- | --- |
| `GET /` | `index.html` from `FRONTEND_DIST` (or JSON 404 if no build) |
| `GET /<path>` | Static file; SPA fallback for `login`, `register`, `rider/*`, `driver/*`, `admin/*`, `test-payment/*`; JSON 404 for `api/*`, `socket.io/*`, dot-files, other unknown paths |

---

## 8. Socket.IO contract (`realtime.py`)

| Item | Value |
| --- | --- |
| Path | `/socket.io` (default) — proxied by Vite in development |
| Transports | client requests `['polling','websocket']` |
| Connect auth | `io({auth: {token: "<access_token>"}})`; invalid/missing → connection refused |
| Rooms | `user:{id}`; admins also `admins` |
| Server → client | `workspace.changed` with `{"event_id": "<uuid>", "server_time": "…Z"}` |
| Client → server | none (besides connect/disconnect) |
| Server disconnects | when the JWT `exp` passes, the session is revoked, or the user is disabled (checked every tick and on logout) |
| Delivery semantics | at-least-once; clients deduplicate by `event_id` and re-fetch `/workspace` |

---

## 9. Endpoints planned in `docs/PRODUCT_BLUEPRINT.md` but **not implemented**

`POST /driver/status`, `GET /driver/invitations`, `GET /driver/earnings`, `POST /maps/routes`, `GET /rides` (list), `GET /admin/rides`, fare-rule/surge-zone CRUD as separate resources, and socket events `invitation.created`, `ride.assigned`, `driver.location_changed`. The implementation replaced these with `/workspace` snapshots and a single `workspace.changed` invalidation event.

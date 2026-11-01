# ridez.io

Taxi booking application built with **React and JavaScript**, Vite, and Flask. Includes mobile/password authentication, role workspaces, GPS driver presence, expanding-radius matching, authenticated Socket.IO updates, and a complete development ride flow: address search → quote → booking → driver acceptance → trip → earnings allocation. Google Maps, Places API (New) autocomplete and server-side Routes API are integrated behind local key configuration. Admins manage versioned INR fares, surge rules, and effective-dated driver/company revenue shares. Payment processing is not connected.

**Google project ready? Follow [Google Maps setup for Windows](docs/GOOGLE_MAPS_SETUP.md)** to configure separate browser/server keys. Without Google configuration, development defaults to explicitly labeled simulator mode. Live Google requests are not exercised by automated tests.

**Existing maps already work?** Enable **Places API (New)** and add it alongside Maps JavaScript API in your existing browser key's allowed APIs. Keep website restrictions and the server Routes key unchanged. See [address search and revenue sharing](docs/ADDRESS_SEARCH_AND_REVENUE.md) for update/test steps.

## Deploy on Render

Use the included [Render deployment guide](docs/RENDER_DEPLOYMENT.md) and root `render.yaml` Blueprint. It builds one Docker web service with HTTPS, Gunicorn, startup migrations and a persistent SQLite disk. A paid instance/disk and Google keys are required for the default live-routing setup. If Render Shell is unavailable, the guide also provides admin creation through runtime Environment settings.

## Run locally

Prerequisites: Node.js 20.19+ (22.12+ recommended), **Python 3.12**, and two terminals. Python 3.14 is not supported by the pinned pyodbc wheel; use 3.12 to avoid compiling it.

### Windows PowerShell

From the repository root (the folder containing `backend` and `frontend`):

```powershell
py -3.12 -m venv backend\.venv312
.\backend\.venv312\Scripts\python.exe -m pip install -r backend\requirements.lock
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

In a second PowerShell terminal, from the repository root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open **http://localhost:5173** for the website. Port 5000 is the backend API; its root URL intentionally returns a JSON 404. `npm.cmd` avoids PowerShell script execution-policy issues. Virtual-environment activation is not required.

To update an existing installation, stop both servers, run `git pull --ff-only` from the repository root, run the dependency install and `flask ... db upgrade` commands again, and restart both servers. Keep your existing virtual environment; creation is only necessary on the first run. Local accounts are preserved by migrations.

### Linux / macOS

Backend, from the repository root:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock
cd backend
.venv/bin/flask --app run db upgrade
.venv/bin/python run.py
```

Frontend, in a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` and `/socket.io` (including WebSockets) to Flask on port 5000. An optional `API_PROXY_TARGET` process variable changes the local proxy destination. Start the backend with **`python run.py`** as shown above: it starts Socket.IO and the background matching loop. `flask run` does not start the matching worker. Drivers start pending approval. Admins can suspend/reinstate approved drivers with a review reason; suspension blocks new work while preserving an assigned trip. See [driver management](docs/DRIVER_MANAGEMENT.md). Admins cannot self-register; create one interactively from `backend` after migrations:

```powershell
# Windows
.\.venv312\Scripts\python.exe -m flask --app run create-admin
```

```sh
# Linux / macOS
.venv/bin/flask --app run create-admin
```

Choose your own admin mobile/password in the prompts. No demo passwords or seeded accounts are included.

## Try one complete simulated ride

1. Register a rider and a driver. Create an admin with the command above.
2. Use separate browsers or private browser windows for the three roles. Sign in as admin and approve the driver with a review reason.
3. Sign in as driver, click **Go available**, and allow location access. Keep the tab open. A fresh location with accuracy within 200 m is required; stale locations older than 90 seconds cannot match or accept. Location is sent immediately, then approximately every 30 seconds while available and every 10 seconds during an assigned trip. Offline/sign-out stops collection; permission revocation attempts to go offline without cancelling an active trip.
4. Sign in as rider and search pickup/destination addresses. In Google mode, select a Google suggestion to fill the address and coordinates automatically. Map clicks and **Use my location** remain available; manual coordinates are under an expandable section. Editing a selected address clears its old coordinates and quote. In simulator mode only pickup coordinates are required. For a quick matching test, use the driver's area as pickup so they are within 500 m. Initial fare defaults are ₹40 base + ₹12/km + ₹2/min, minimum ₹40, with surge off. Admins can change future quote rates under **Fare settings**. Google mode uses road distance/duration; simulator mode uses sample metrics.
5. Confirm the ride. Search starts at **500 m**, expands **500 m every 30 seconds**, and defaults to a **5 km maximum** (ten rounds / five minutes). Each newly eligible driver gets one invitation per ride. Accept within the invitation deadline, then select **Head to pickup → I’ve arrived → Enter rider OTP → Start trip → Complete trip**. Socket.IO pushes state invalidations; the client fetches authoritative state on events/reconnect and periodically reconciles via API. If the socket is unavailable, two-second polling continues.
6. Review ride history and driver earnings. Completion records one allocation using the revenue split effective at completion (85/15 initially). Admins can set immediate/future splits under **Revenue share**, with reasons and immutable audit versions. Recorded allocations never change when settings change. No payment or transfer occurs. When a trip completes, the rider chooses **Pay online** (test QR, when enabled) or **Pay by cash**. The driver's overview shows a **Collect payment** card with **Cash received**; online payments confirm automatically when successful. The first confirmation wins and is final. A trip's driver share counts toward **Earnings received** only after its payment is confirmed; until then it appears under **Awaiting payment**. Trips completed before payment tracking existed are treated as already paid. An active driver with fresh GPS stays available after completion and can receive another ride. Uncheck **Stay available after this trip** to finish offline; logout, suspension, denied permission and stale GPS prevent automatic availability.

Riders see their fare breakdown and trip details only. Driver/company allocations are excluded from rider API responses and rider screens, including completed-trip history and repeat booking responses. Assigned drivers and admins retain their authorized financial views.

The admin overview shows live ride counts, fresh/stale available drivers, pending applications and all-time recorded allocations. **Audit history** provides paginated category/search filters and before/after details for driver approvals, fare policies and revenue settings. See [admin monitoring and privacy](docs/ADMIN_MONITORING.md).

The quote expires after five minutes. Retrying a booking with the same quote returns the same ride. One active ride per participant is enforced through unique database claims. Newly available drivers can be invited in subsequent rounds if fresh and in range, but a driver is never repeatedly invited for the same ride. Riders can cancel searches, and the rider or assigned driver can cancel before the trip starts with a reason. Both participants see the recorded cancellation; claims are released and assigned drivers remain offline. In-progress interruption remains a separate incident workflow. See [pre-trip cancellation](docs/CANCELLATIONS.md).

Matching deadlines, round history, invitations, and outgoing events are persisted in the database. A one-second background loop advances overdue rounds and marks stale locations even without API traffic. After a restart it catches up to persisted deadlines, skips invitations for already-expired rounds, and resumes pending event delivery. Events can be retried; clients deduplicate IDs and fetch current state. Matching/acceptance use conditional writes and unique participant claims. Final timeout releases the rider's active claim. Set `MATCH_MAX_RADIUS_M` to a 500 m increment between 500 and 10000 to change the search limit. In simulator mode, `SIMULATOR_ENABLED=0` blocks new sample quotes/bookings/online availability/acceptances; going offline and completing assigned rides remain possible. Google mode does not depend on this flag. The simulator defaults off outside development, where the default route provider is Google. A route-provider change requires generating a new quote.

Fare policies are immutable versions with admin ID, change reason and timestamp. Quotes snapshot distance/time components, minimum adjustment, surge amount/reason, and the policy version; later rate changes cannot reprice an existing quote or settlement. Components are rounded to two decimals; time is prorated from route seconds and distance uses exact metres. Eligible surge rules use the highest multiplier, capped globally. Quotes expire after five minutes; the quote endpoint limits each rider to ten attempts per minute in the single-process development limiter. Production needs shared quota/rate controls.

### Location troubleshooting

Browser geolocation requires **HTTPS or localhost**. Allow site location access and enable OS location services. A coarse fix worse than 200 m, stale timestamp, implausible jump, or permission denial is rejected with a visible error. If your desktop cannot obtain a precise fix, use Chrome/Edge DevTools → More tools → Sensors to set a custom test location, and enter matching pickup coordinates in the rider form. This overrides only that browser's reported test position; it does not provide a real GPS service. Production background tracking will require a native/mobile implementation because browsers throttle hidden tabs.

The backend keeps only the latest driver location, not a tracking history. Ordinary users cannot write another driver's location or subscribe to arbitrary rooms. Admin views show freshness/accuracy without exposing precise location coordinates. Invitation/ride details are scoped to their participants and admins.

Development defaults to SQLite and persists random local signing/code secrets under ignored `backend/instance/`. Never use these defaults as a production configuration. Access tokens remain in browser memory and expire after 15 minutes. A rotating HttpOnly refresh cookie restores sign-in on reload for up to 30 days. Sign-out revokes the current server session; **Your account → Sign out all devices** revokes every session for that account. See [persistent sessions](docs/SESSIONS.md). The auth rate limiter is single-process development protection; replace it with shared Redis-backed limits before deployment.

## SQL Server and deployment

The SQLAlchemy models and Alembic migrations target SQL Server. Set `DATABASE_URL` with the `mssql+pyodbc` dialect and install Microsoft ODBC Driver 18 before using SQL Server. Supply `JWT_SECRET` and `USER_CODE_SECRET` as distinct strong secrets through environment settings; see `backend/.env.example`. `backend/.env` is loaded at startup without overriding existing process variables. Vite reads `frontend/.env.local`. Both are ignored by Git; examples contain placeholders only. Outside development, set `APP_ENV=production`; database and secrets become mandatory. SQL Server connectivity/concurrency has not been validated in this instance. The Render image uses Gunicorn; `python run.py` remains the local development server.

Current realtime/worker runtime is **one server process**, intentionally avoiding a separate Redis install for local Windows development. Do not run multiple API workers/instances with this in-process socket dispatcher: production scaling needs a shared message broker, worker ownership and SQL Server integration tests. The Render package supplies a supervised single-worker Gunicorn/Socket.IO server; it does not enable multiple instances. `/api/v1/health` reports `matching_worker: true` after successful background ticks; false means the loop has not started or is failing/stalled. Delivered outbox records are pruned after seven days. Undelivered events remain for retry.

Run migrations with `.venv/bin/flask --app run db upgrade`. Never change existing account-code secrets without a migration plan. No database credentials belong in frontend variables. All business APIs must enforce permissions server-side.

## Validation

```sh
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm run build
```

API specification: `/api/v1/openapi.json`; Swagger UI: `/api/v1/docs` (requires access to jsDelivr). Health: `/api/v1/health`. Backend tests currently exercise SQLite; they do not establish SQL Server transaction behavior.

## Product plan

- [Product blueprint](docs/PRODUCT_BLUEPRINT.md)
- [Screen flows](docs/SCREEN_FLOWS.md)
- [Google Maps setup and validation](docs/GOOGLE_MAPS_SETUP.md)
- [Address search and revenue sharing](docs/ADDRESS_SEARCH_AND_REVENUE.md)
- [Admin monitoring and rider financial privacy](docs/ADMIN_MONITORING.md)

Verified on SQLite: authentication and role checks, quote ownership/expiry, repeat booking/completion, invalid transitions, cancellation and invitation expiry, simultaneous drivers accepting one ride, and simultaneous rides competing for one driver. New checks cover coordinate/time validation, replay and implausible movement, 90-second freshness, radius expansion, no repeat invitations, idempotent deadline recovery without HTTP traffic and from a new app instance, socket access/expiry, and outbox retries. These checks do not establish SQL Server concurrency behavior. Browser checks cover GPS permission, immediate and 30-second reports, revocation going offline, denial blocking availability, fresh availability, actual WebSocket notifications, admin approval through rider completion/earnings, persisted history after re-login, and mobile layout.

Google/fare tests verify outgoing request shape, no fallback on provider failure, missing traffic, quotas/timeouts, decimal rounding, minimums/caps, timezone/overnight schedules, optimistic policy updates, demand signals, immutable quotes, and role access. Browser tests use explicit map/route fixtures for the full pricing-to-settlement flow. Actual Google map tiles, live keys/restrictions, billing and Google-produced route estimates require local verification with your keys; see the setup guide.

Revenue tests cover role restrictions, percentage bounds/sums, immediate/future effective dates, exact activation boundaries, revision conflicts, rounding/100–0 splits, and unchanged historical allocations after edits/retries. Places browser tests use provider fixtures for debouncing, keyboard/click selection, stale result suppression, coordinate/quote invalidation, error states, and end-to-end settlement with edited splits. Verify your live Places key restrictions locally after enabling Places API (New).

Privacy/admin tests verify rider settlement exclusion across API responses, preserved fare/driver details, driver/admin financial access, audit authorization/search/pagination, before/after values, live counters and stale-driver totals. Browser checks cover rider receipts/history (including defensive handling of a stale payload), driver earnings, audit filters/details and mobile layout.

Remaining milestones include incident support, account recovery, commercial cancellation/no-show policies, payment integration, SQL Server integration tests, and production operations. Commercial rate/fee policies and provider billing/retention terms require launch review.

### Per-ride trip OTP

Each ride has its own six-digit OTP, shown to the rider from booking until the trip starts. It stays the same across sign-ins and restarts for that ride, but a code from one ride can never start another. At pickup, the rider shares it with the assigned driver, who must enter it before starting a waiting trip. Missing or incorrect codes leave the trip waiting. Driver/admin API responses never include the code. Start retries require the same code and remain idempotent.

Codes are derived with a separate HMAC domain from the rider account code and `USER_CODE_SECRET`; keep that secret stable, as required for existing account codes. No schema migration is needed. Failed OTP checks are limited to five per driver per minute in the single-process development runtime; production needs shared rate limiting. This is a reusable pickup PIN, not an SMS or expiring code.

Session checks cover single-use refresh rotation, replay revocation, absolute expiry, disabled accounts, cross-origin/CSRF rejection, device-specific and all-device logout, socket disconnection, concurrent refresh, restart persistence and preserved driver assignments. The session migration adds two tables and preserves existing accounts; existing access tokens require a fresh sign-in after upgrading.

Driver review tests cover status/version validation, idempotent retries, immutable audit snapshots, admin-only access, searchable paginated lists, suspended matching exclusion and continued assigned-trip tracking/OTP completion. SQLite concurrency checks cover competing admin decisions and suspension racing availability/acceptance. SQL Server concurrency still requires integration validation.

### Embedded Google trip maps

The rider and assigned driver see Google’s road route inside their active trip screen, including after reload. While the driver is assigned or heading to pickup, the route runs from the driver’s latest fresh GPS fix to the pickup, and the rider sees how far away (km and minutes) the driver is. Once the driver arrives, the map shows the pickup-to-destination route. On trip start, the route switches from the driver’s latest fresh GPS fix to the destination. A taxi marker updates from fresh driver location; stale/missing GPS hides the marker and labels the pickup-to-destination fallback. The browser checks every 10 seconds; server-side road routes are refreshed at most once per minute per ride/phase/source and shared between participants to limit Google billing. These are Google Routes results, not invented straight lines, and route updates never reprice the confirmed fare.

Above the map, rider and driver see a large trip card: time and distance to pickup with the expected arrival while the driver is on the way, the booked trip time and distance while waiting at pickup, and time left, distance left and arrive-by time during the trip. The driver's card has a **Navigate in Google Maps** button (to the pickup before arrival, to the destination during the trip). It opens Google Maps in a new tab or the Maps app so ridez.io stays open; turn-by-turn navigation inside the website is not offered because Google provides it only through its native mobile Navigation SDK. Phones may pause browser location updates while Maps is in front.

The embedded map is a road-route view, not Google’s voice-guided navigation app. Only the rider and assigned driver can fetch the active map; admin/history endpoints do not expose this live position. Route failures have a visible retry state and do not block trip controls. The current Maps JavaScript/Routes keys are reused; no migration or additional Google API is required. Live provider billing and route accuracy still require verification with your configured keys.

### Prominent pickup and ride details

After acceptance, rider screens put driver name, car number, model/colour, confirmed fare, pickup/destination and the pre-start OTP in a prominent card. Driver screens emphasize rider name, assigned car, fare and the next trip action. Essential details precede the map on mobile; detailed fare calculations are expandable. No ratings, driver photos, pickup ETAs or vehicle details are invented.

Record actual car details under **Admin → Drivers → Vehicle details** before the next booking. Each accepted ride snapshots the car number/model/colour. The admin cannot change the vehicle during an active trip, and later updates do not rewrite completed trips. Existing drivers/rides without recorded details show an explicit missing-information message. This update requires `flask --app run db upgrade` locally; Render applies migrations on startup. There are no new dependencies. See [vehicle and pickup details](docs/VEHICLE_DETAILS.md).

Mock QR payment testing: see [TEST_PAYMENTS.md](TEST_PAYMENTS.md) for Render setup and the scan/simulate flow.

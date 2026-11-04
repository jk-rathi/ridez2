# 21 — Quick revision sheet

[← Back to index](README.md)

## Technologies and responsibilities

| Tech | Job |
| --- | --- |
| React 19 + React Router 7 + Vite 6 | SPA, routing, dev proxy, build |
| socket.io-client / Flask-SocketIO (threading) | `workspace.changed` push |
| Flask 3.1 + Blueprint `api` at `/api/v1` | REST API |
| SQLAlchemy 2.1 + Flask-Migrate/Alembic | ORM + 13 migrations (head `c51e8a2f90d4`) |
| SQLite (dev + Render) / SQL Server (untested target) | DB |
| PyJWT HS256 | 15-min access tokens |
| Werkzeug | password hashing, ProxyFix |
| phonenumbers | E.164 mobiles |
| requests | Google Routes |
| itsdangerous | mock QR tokens |
| Gunicorn 1 worker gthread 100 threads | production server |
| Docker + Render + GitHub Actions | deploy + CI |

## Key file paths

| Path | One-liner |
| --- | --- |
| `backend/app/__init__.py` | `create_app`, config validation, CLI |
| `backend/app/models.py` | 19 tables |
| `backend/app/routes.py` | blueprint, `authenticated`, auth/health/ready |
| `backend/app/ride_routes.py` | rides, driver, admin routes |
| `backend/app/test_payment_routes.py` | mock QR |
| `backend/app/ride_service.py` | quote, book, availability, accept, move, snapshot |
| `backend/app/matching.py` | invite, advance |
| `backend/app/ride_repository.py` | assign, transition, expire_round, locks, notify |
| `backend/app/session_service.py` | JWT, refresh rotation, logout, check_origin |
| `backend/app/services.py` | ApiError, register, login, trip OTP |
| `backend/app/fare_service.py` | policy, calculate, surge |
| `backend/app/route_provider.py` | Google/simulator routes |
| `backend/app/location_service.py` | GPS validation, freshness, haversine |
| `backend/app/payment_service.py` | payment choose/confirm |
| `backend/app/revenue_service.py` | split versions, allocate |
| `backend/app/rating_service.py` | ratings |
| `backend/app/admin_service.py` | metrics, audit, driver status, vehicles |
| `backend/app/trip_map_service.py` | live map + cache |
| `backend/app/realtime.py` | sockets, dispatch, worker |
| `backend/app/web.py` | SPA serving + security headers |
| `backend/run.py` / `wsgi.py` / `gunicorn.conf.py` | entry points |
| `frontend/src/main.jsx` | routes, AuthProvider, Workspace |
| `frontend/src/authSession.js` / `api.js` | session store / fetch wrapper |
| `frontend/src/RideWorkspace.jsx` | role dashboards, `useWorkspace`, `perform` |
| `frontend/src/BookingPanel.jsx`, `AddressSearch.jsx` | booking |
| `frontend/src/useDriverLocation.js` | GPS loop |
| `frontend/src/TripRouteMap.jsx`, `TripStatsCard.jsx`, `GoogleRouteMap.jsx` | maps |
| `frontend/src/TestPayment.jsx`, `PaymentStatus.jsx`, `Rating.jsx` | payments, ratings |
| `frontend/src/DriverManagement.jsx`, `FareSettings.jsx`, `RevenueSettings.jsx`, `AdminAudit.jsx` | admin |
| `deploy/start.sh`, `Dockerfile`, `render.yaml` | deployment |

## Main functions

`create_app` · `authenticated(role)` · `session_service.authenticate/issue/refresh/logout/stop_requests/check_origin` · `services.register/login/normalize/trip_otp/verify_trip_otp` · `ride_service.quote/book/availability/accept/reject/move/snapshot/public/expire/accessible` · `matching.invite/advance/close_round` · `ride_repository.assign/transition/expire_round/eligible_drivers/lock_active_driver/notify/notify_ride/release` · `location_service.update/is_fresh/distance_m` · `route_provider.compute` · `fare_service.calculate/validate/save/scheduled/demand_signal` · `revenue_service.active/save/allocate` · `payment_service.choose/confirm/confirm_cash` · `rating_service.submit/summary` · `admin_service.change_driver_status/save_driver_vehicle/driver_list/audit/audit_detail/metrics` · `trip_map_service.trip_map/cached_route` · `realtime.tick/dispatch/start_worker` · Frontend: `api`, `refreshSession`, `signIn`, `signOut`, `useWorkspace`, `perform`, `useDriverLocation`, `getPosition`, `useTripRoute`, `usePaymentPrompt`.

## API endpoints (`/api/v1`)

| Auth | Endpoints |
| --- | --- |
| public | `GET /health`, `GET /ready`, `GET /openapi.json`, `GET /docs`, `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`*, `POST /auth/logout`*, `GET/POST /test-payments/{token}` |
| any signed in | `GET /me`, `GET /workspace`, `GET /rides/{id}`, `POST /rides/{id}/{depart\|arrive\|start\|complete\|cancel}`, `POST /auth/logout-all`* |
| rider | `POST /fares/quotes`, `POST /rides`, `POST /rides/{id}/payment-method`, `POST /rides/{id}/test-payment` |
| driver | `POST /driver/availability`, `PUT /driver/location`, `GET /driver/overview`, `POST /rides/{id}/accept\|reject\|confirm-cash` |
| rider or driver | `POST /rides/{id}/rating`, `GET /rides/{id}/map` |
| admin | `GET /admin/overview`, `GET /admin/drivers`, `POST /admin/drivers/{id}/approve\|suspend\|reinstate`, `PUT /admin/drivers/{id}/vehicle`, `GET/PUT /admin/fare-settings`, `GET/PUT /admin/revenue-share`, `GET /admin/audit`, `GET /admin/audit/{category}/{id}` |

\* cookie endpoints need `X-Session-Request: 1`. Socket.IO: connect with `auth.token`; event `workspace.changed {event_id, server_time}`.

## Database models

`User`(users) · `DriverPresence` · `DriverLocation` · `DriverVehicle` · `FareQuote` · `FarePolicy` · `Ride` · `ActiveRide` · `Invitation`(ride_invitations) · `MatchRound`(ride_match_rounds) · `OutboxEvent` · `RevenueLedger` · `RevenueShareSetting` · `AdminAudit` · `AuthSession` · `RefreshToken` · `RidePayment` · `MockPayment` · `RideRating`

Ride states: `SEARCHING → ASSIGNED → ARRIVING → WAITING → IN_PROGRESS → COMPLETED`; terminal `CANCELLED`, `NO_DRIVER_FOUND`.

## Environment variables (names only)

Backend: `APP_ENV`, `DATABASE_URL`, `JWT_SECRET`, `USER_CODE_SECRET`, `ROUTE_PROVIDER`, `GOOGLE_MAPS_SERVER_KEY`, `SIMULATOR_ENABLED`, `TEST_PAYMENTS_ENABLED`, `MATCH_MAX_RADIUS_M`, `AUTH_TRUSTED_ORIGINS`, `TRUST_PROXY_HEADERS`, `PORT`, `BOOTSTRAP_ADMIN`, `BOOTSTRAP_ADMIN_MOBILE`, `BOOTSTRAP_ADMIN_NAME`, `BOOTSTRAP_ADMIN_PASSWORD`.
Frontend/build: `VITE_GOOGLE_MAPS_BROWSER_KEY`, `VITE_GOOGLE_MAP_ID`, `API_PROXY_TARGET`. Render native: `PYTHON_VERSION`, `NODE_VERSION`. Browser test: `RIDEZ_TEST_URL`, `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH`.

## Numbers to remember

| Value | Meaning |
| --- | --- |
| 15 min / 30 days | access token / session lifetime |
| 5 min | quote validity |
| 500 m, +500 m / 30 s, 5 km | matching radius start/step/max (10 rounds) |
| 90 s | location freshness |
| 200 m | max GPS accuracy |
| 200 km/h | implausible-movement threshold (+ accuracies + 100 m) |
| 30 s / 10 s | location send interval idle / on trip |
| 2 s / 15 s | workspace poll without / with socket |
| 10 s | trip map refresh; worker health window |
| 60 s | trip map Google cache |
| 1 s | worker tick |
| 200 | outbox events per tick |
| 7 days | outbox retention; rating form window (UI) |
| 10/min | login+register per IP; quotes per rider |
| 5/min | failed OTPs per driver |
| 15 min | mock QR link |
| ₹40 + ₹12/km + ₹2/min, min ₹40 | default fare |
| 85 / 15 | default driver/company split |
| 20 | max surge zones; page size |
| 100 | rides/drivers in snapshot |

## Important workflows (one line each)

1. **Register** → E.164 → HMAC code → hash → users (driver pending).
2. **Login** → session + refresh cookie + 15-min JWT; reload → `/auth/refresh`.
3. **Driver online** → GPS fix → `/driver/availability` → presence + location → stale after 90 s.
4. **Quote** → Google/simulator route → fare (+surge) → `fare_quotes` (5 min).
5. **Book** → ride SEARCHING + rider claim + round 1 invitations + outbox.
6. **Match** → every 30 s radius +500 m; max → NO_DRIVER_FOUND.
7. **Accept** → conditional assign + driver claim + vehicle snapshot.
8. **Trip** → depart → arrive → start (OTP) → complete.
9. **Complete** → ledger split + payment PENDING + release + auto-availability.
10. **Pay** → cash (driver confirms) or mock QR → first confirmation wins.
11. **Rate** → once per side; comments admin-only.
12. **Admin** → approve/suspend/reinstate with version + reason; fares; revenue; audit.
13. **Real-time** → outbox → worker emits → client refetches `/workspace`.

# 14 — Error handling and edge cases

[← Back to index](README.md) · Next: [15 — Deployment and execution →](15-deployment-and-execution.md)

## 1. Mechanisms

| Layer | Mechanism | File |
| --- | --- | --- |
| Domain | `raise ApiError(message, status)` | `services.py` (class), all services |
| Blueprint | `@api.errorhandler(ApiError)` → `{"error": message}`, status, `no-store`; 401 on refresh/logout-all clears cookie | `routes.py::api_error` |
| App | JSON 404 `Resource not found`, 405 `Method not allowed` | `__init__.py` |
| Transactions | `repo.rollback()` / `db.session.rollback()` before raising after failed conditional writes; Flask-SQLAlchemy removes the session at teardown | services |
| Worker | rollback + generic log line, retry next second | `realtime.py` |
| Frontend | `api()` throws `Error(data.error)`; components show it | `api.js` |

## 2. Status code usage

| Code | Meaning in this app | Examples |
| --- | --- | --- |
| 400 | Validation failure | missing/invalid fields, wrong OTP, non-object JSON |
| 401 | Not authenticated | bad/expired JWT, revoked session, wrong credentials |
| 403 | Authenticated but not allowed | wrong role, inactive driver, CSRF/origin check |
| 404 | Not found **or not yours** | ride not accessible, invitation missing, feature disabled (test payments) |
| 409 | State conflict / race lost / stale version | quote expired, ride changed, already accepted, stale admin version |
| 410 | Expired capability | mock QR token expired |
| 422 | Semantically impossible | no driving route, fare above maximum |
| 429 | Rate limit / busy | auth, quotes, OTP, trip-map cache full |
| 502 | Upstream failure | Google denied / invalid / unavailable |
| 503 | Feature/dependency unavailable | simulator disabled, Google key missing, quota, not ready |
| 504 | Upstream timeout | Google timeout, trip-map wait > 15 s |

## 3. Scenario table

| Scenario | Handling | Where |
| --- | --- | --- |
| Invalid user input | Explicit type/range/length checks; `bool` rejected for numbers; messages name the field | every service |
| Missing body / not JSON object | 400 `A JSON object is required` | `routes.body` |
| Missing required data | e.g. `A quote_id is required`, `Reason must contain 1–300 characters` | services |
| Unauthorized | 401/403 via `authenticated`; 404 for foreign resources | `routes.py`, `ride_service.accessible` |
| Invalid / expired token | 401 `Please sign in again`; frontend refreshes once and retries | `session_service.authenticate`, `api.js` |
| Refresh token reuse | Session revoked, 401, cookie cleared | `session_service.refresh` |
| Database integrity race | `IntegrityError` caught → idempotent return or 409 | `book`, `accept`, `availability`, `register`, `rating_service.submit`, `fare_service.save`, `revenue_service.save`, `create_test_payment` |
| Lost conditional update | rollback + 409 `… changed. Refresh and retry` | `move`, `accept`, `change_driver_status`, `payment_service` |
| Duplicate requests | Idempotent handlers return the current state | booking (quote id), accept, reject, transitions, cancel, review, payment choice/confirm, mock status, same-star rating |
| Concurrent requests | Exactly one winner by conditional writes and PKs; tested with thread barriers on SQLite | see [03 §12](03-system-architecture.md#12-concurrency-model-critical-to-understand) |
| Empty responses | `rides: []`, `invitations: []` with empty-state UI; Google `routes: []` → 422 | |
| Network failure (client) | `fetch` rejects → error banner; polling continues (2 s) and recovers; actions disabled while `error` set | `useWorkspace` |
| Unreadable server response | `Unable to read the server response. Please retry.` | `api.js` |
| External API failure | Mapped 502/503/504/422 with safe messages; no simulated fallback | `route_provider.compute` |
| Timeouts | Google 3 s/10 s; trip-map wait 15 s; Maps script 15 s; geolocation 15 s + 20 s | various |
| Database failure | Unhandled `SQLAlchemyError` → Flask 500 (not JSON); `/ready` reports `database:false`; worker logs and retries | — |
| Worker crash | Exceptions caught per tick; deadlines still advanced by request traffic | `realtime.py` |
| Server restart mid-search | Deadlines persisted; catch-up replays rounds without inviting into expired rounds | `matching.advance` |
| Trip completes during map fetch | Re-check after Google call → 409, no driver coordinates | `trip_map_service` |
| Driver loses GPS mid-trip | Map falls back to pickup route; completion still allowed; not auto-available after | `trip_map_service`, `move` |
| Suspended driver mid-trip | Can track, start with OTP, complete; earnings recorded | `location_service.update`, tests |
| Quote from other provider mode | 409 `Route mode changed…` | `book` |
| Expired QR | 410 with guidance | `payment_for` |

## 4. Edge cases worth knowing

- **Start retry requires the OTP again** because the OTP check runs when status is `WAITING` *or* `IN_PROGRESS`.
- **Cancel without reason** is only accepted for SEARCHING rides and only if the `reason` key is absent (an empty string fails validation).
- **Invitation acceptance after round expiry**: rejected even if the invitation row still says PENDING, because `assign()` checks `Invitation.expires_at > now` and `Ride.expires_at > now`.
- **Driver goes offline with invitations open**: invitations become `OFFLINE`; ride keeps searching.
- **`reject` for a non-pending invitation** returns its current status instead of an error.
- **Admin approve without version** (legacy) is allowed and idempotent.
- **Rider rating window**: the backend accepts ratings at any time after completion; only the UI hides the form after 7 days.

## 5. Missing error handling / failure points

| Gap | Impact | Recommendation |
| --- | --- | --- |
| No JSON handler for 500 / unexpected exceptions | Clients receive Flask's HTML 500; `api()` then shows "Unable to read the server response" | Add `@app.errorhandler(Exception)` returning `{"error": "Unexpected server error"}` and logging with a request ID |
| No request IDs / structured logging | Hard to correlate errors | Add a request-ID middleware and JSON logs |
| SQLite `database is locked` under load | Surfaces as 500 | Configure SQLite busy timeout / WAL, or move to a server DB |
| Google quote calls not retried | User must retry manually | Optional single retry with jitter for 5xx/timeouts |
| Outbox dispatch emits before commit | Duplicate emits after crash (harmless) | Acceptable; documented as at-least-once |
| Frontend has no error boundary | A render error blanks the app | Add a top-level React error boundary |
| `disconnect_invalid` and `dispatch` run DB queries per socket per second | Load grows with connections | Batch session validation |
| No timeout on SQLAlchemy queries | A stuck DB blocks a thread | Set statement timeouts on the server DB |

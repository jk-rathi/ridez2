# 13 — Background processes and real-time functionality

[← Back to index](README.md) · Next: [14 — Error handling →](14-error-handling.md) · Diagrams: [diagrams/realtime.md](diagrams/realtime.md)

## Inventory

| Mechanism | Implemented? | Where |
| --- | --- | --- |
| Background worker loop (1 s) | ✓ | `backend/app/realtime.py::start_worker/tick` |
| WebSockets (Socket.IO) | ✓ | `realtime.py`, `RideWorkspace.jsx::useWorkspace` |
| Transactional outbox | ✓ | `outbox_events`, `ride_repository.notify`, `realtime.dispatch` |
| Client polling | ✓ | `/workspace` every 2 s/15 s; `/rides/{id}/map` every 10 s |
| Location tracking | ✓ (browser foreground only) | `useDriverLocation.js` |
| Deadline-based scheduling | ✓ (persisted in DB) | `rides.expires_at`, `matching.advance` |
| Cron jobs / task queues / Celery / Redis | ✗ | — |
| Push notifications / SMS / email | ✗ | — |
| Retry mechanisms | ✓ for outbox delivery, refresh scheduling, location loop, Google map polling; ✗ for Google quote calls (user retries) | |

## 1. The worker loop

**Start:** `start_worker(app)` is called once per process — by `run.py` before `socketio.run`, or by Gunicorn's `post_worker_init` hook. It is guarded by `app.extensions['matching_worker']` so it never starts twice in the same app.

```python
def start_worker(app):
    if app.extensions.get('matching_worker'): return
    def loop():
        while True:
            try: tick(app)
            except Exception:
                app.logger.error('Matching worker tick failed; retrying. Check database readiness and migrations.')
            socketio.sleep(1)
    app.extensions['matching_worker'] = socketio.start_background_task(loop)
```

With `async_mode='threading'`, `start_background_task` starts a regular daemon thread **(inferred from Flask-SocketIO threading mode)**.

**`tick(app)`**:

```python
with app.app_context():
    try:
        advance()     # matching + stale GPS
        dispatch()    # sockets + outbox
        app.extensions['matching_last_tick'] = time.monotonic()
    except Exception:
        db.session.rollback(); raise
```

`matching_last_tick` drives `/health.matching_worker` and `/ready` (must be < 10 s old).

### What `advance()` does each second

1. Find SEARCHING rides whose `expires_at <= now`.
2. For each, claim the round with a conditional UPDATE (`expire_round`), so HTTP requests running `advance()` concurrently cannot double-process it.
3. Expire PENDING invitations, mark the round `EXPIRED`.
4. If max radius reached → `NO_DRIVER_FOUND`, release the rider's claim. Else radius += 500 m, deadline += 30 s, invite newly eligible drivers.
5. Notify the rider, invitees and admins; commit per ride.
6. Repeat up to `MATCH_MAX_RADIUS_M/500 + 1` times to catch up after downtime.
7. Mark `driver_locations` older than 90 s as `fresh=False` and notify those drivers.

Because the same `advance()` runs at the start of most HTTP requests (`ride_service.expire()`), the system also progresses if the worker thread dies — but only while there is traffic.

## 2. Outbox → Socket.IO

**Writing events.** Any service that changes state visible to a user calls:

```python
def notify(*user_ids):
    for user_id in set(user_ids) | {None}:          # always one extra event for admins
        add(OutboxEvent(id=str(uuid4()), user_id=user_id, created_at=utcnow()))
```

The rows are committed **in the same transaction** as the business change. If the transaction rolls back, no event is emitted; if it commits, the event is guaranteed to be delivered eventually.

Who notifies whom:

| Operation | Recipients |
| --- | --- |
| Book, round expiry, accept, trip transitions, cancel | rider, all invited drivers, assigned driver, admins (`notify_ride`) |
| Availability change, location update, stale sweep, reject | that driver, admins |
| Driver status change, vehicle save | that driver, admins |
| Fare/revenue settings save | admins only (`notify()` with no ids) |
| Payment method / cash confirm / mock status | rider, driver, admins |
| Logout / session revocation (drivers) | that driver, admins |
| Rating | none |

**Delivering events.** `dispatch()`:

```python
disconnect_invalid()
events = SELECT * FROM outbox_events WHERE delivered_at IS NULL ORDER BY created_at LIMIT 200
for event in events:
    socketio.emit('workspace.changed', {'event_id': event.id, 'server_time': now},
                  to=f'user:{event.user_id}' if event.user_id is not None else 'admins')
    event.delivered_at = now
DELETE FROM outbox_events WHERE delivered_at < now - 7 days
COMMIT
```

- Delivery is **at-least-once**: if the process dies after emitting but before committing, the events are re-emitted.
- Events are emitted even if the user is offline (no connected sockets) — they are simply marked delivered; the client catches up by polling/refetching on reconnect.
- At most 200 events per second are delivered; a backlog drains over subsequent ticks.

**Socket authentication** (`connect` handler): validates `auth.token` exactly like HTTP. Accepted sockets join `user:{id}` (and `admins` for admins). `disconnect_invalid()` checks every tracked socket each tick for JWT expiry, disabled user, or revoked session, and force-disconnects it.

**Client handling** (`useWorkspace`): dedupe by `event_id` (keeps the last 100 IDs), debounce 80 ms, refetch `/workspace`. The token-dependent effect reconnects the socket after each token refresh.

## 3. Polling

| Poll | Interval | Purpose |
| --- | --- | --- |
| `/workspace` | 15 s when socket live, 2 s otherwise | Reconciliation and fallback |
| `/rides/{id}/map` | server-suggested `refresh_after_seconds` (10 s); 15 s after an error | Live route + driver marker |
| Session renewal | `expires_at − 60 s`; retry 15 s | Keep access token valid |
| Countdown display | 500 ms (`setInterval`) | UI only |

## 4. Location tracking

- Starts when a driver is available or has an active ride (`useDriverLocation` `enabled`).
- Sends immediately, then every 30 s (idle) or 10 s (on trip).
- Server freshness window: 90 s; worker marks stale within ~1 s of crossing it.
- Permission revocation (Permissions API `change` event) or a denial error triggers `POST /driver/availability {available:false}` — new matching stops, the active trip is preserved.
- Limitation: browsers throttle timers in background tabs and mobile browsers may suspend pages, so a driver who switches apps can become stale. The README notes native background tracking would require a mobile app.

## 5. Time-based rules summary

| Rule | Value | Enforced by |
| --- | --- | --- |
| Quote validity | 5 min | `quote()` sets `expires_at`; `book()` checks |
| Matching round | 30 s (`MATCH_ROUND_SECONDS`) | `rides.expires_at`, `advance()` |
| Max search | `MATCH_MAX_RADIUS_M/500` rounds (default 10 → 5 min) | `advance()` |
| Location freshness | 90 s (`LOCATION_STALE_SECONDS`) | `is_fresh`, `eligible_drivers`, `assign`, stale sweep |
| Location future tolerance | 15 s | `location_service.update` |
| Access token | 15 min | `session_service.payload` |
| Session | 30 days absolute | `issue()` |
| Mock QR link | 15 min | `payment_for` `max_age=900` |
| Trip map cache | 60 s success / 10 s error | `cached_route` |
| Recent cancellation banner | 10 min | `snapshot()` |
| Rating form shown | 7 days (UI only) | `RATING_WINDOW_MS` |
| Payment prompt on reload | 30 min (UI only) | `usePaymentPrompt` |
| Outbox retention | 7 days after delivery | `dispatch()` |
| Rate-limit windows | 60 s | limiters |

## 6. Why single-process matters

The following live only in process memory: Socket.IO connections and rooms, `ride_connections` map, rate-limit buckets, trip-map cache, `matching_last_tick`. Running two Gunicorn workers or two instances would mean: a user connected to worker A would miss emits from worker B's dispatcher (Socket.IO has no message queue configured), rate limits would be per-worker, and readiness would reflect only one worker. Both worker loops would still be **safe** for matching (conditional claims), but notifications would be lost. This is why `gunicorn.conf.py` sets `workers = 1` and `render.yaml` sets `numInstances: 1`.

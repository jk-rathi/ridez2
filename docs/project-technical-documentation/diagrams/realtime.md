# Real-time and background processing diagrams

[← Back to index](../README.md) · Details: [13 — Background and real-time processes](../13-background-and-realtime-processes.md)

## Worker loop (`backend/app/realtime.py`)

```mermaid
flowchart TD
  start["start_worker(app)<br/>(run.py main or gunicorn post_worker_init)"] --> guard{"app.extensions['matching_worker'] set?"}
  guard -- yes --> stop([return])
  guard -- no --> bg["socketio.start_background_task(loop)"]
  bg --> loop["while True"]
  loop --> tick["tick(app): with app_context"]
  tick --> adv["matching.advance()<br/>expire rounds, expand radius, NO_DRIVER_FOUND,<br/>mark stale GPS"]
  adv --> disp["dispatch()"]
  disp --> dis["disconnect_invalid()<br/>drop sockets with expired JWT / revoked session / disabled user"]
  dis --> fetch["SELECT ≤200 outbox_events WHERE delivered_at IS NULL ORDER BY created_at"]
  fetch --> emit["socketio.emit('workspace.changed', {event_id, server_time})<br/>to room user:{id} or 'admins'"]
  emit --> mark["delivered_at = now"]
  mark --> prune["DELETE delivered events older than 7 days"]
  prune --> commit["COMMIT"]
  commit --> stamp["extensions['matching_last_tick'] = monotonic()"]
  stamp --> sleep["socketio.sleep(1)"]
  tick -. exception .-> log["rollback, log generic error (no payload)"] --> sleep
  sleep --> loop
```

## Transactional outbox pattern

```mermaid
sequenceDiagram
  participant H as HTTP handler (e.g. accept)
  participant DB as DB transaction
  participant W as Worker tick (≤1 s later)
  participant S as Socket.IO room
  participant C as useWorkspace (RideWorkspace.jsx)
  H->>DB: business writes (rides, invitations, ...)
  H->>DB: INSERT outbox_events per affected user + one with user_id NULL (admins)
  H->>DB: COMMIT (events exist only if business change committed)
  W->>DB: read undelivered events
  W->>S: emit workspace.changed {event_id}
  W->>DB: delivered_at = now, COMMIT
  S->>C: event
  C->>C: dedupe by event_id (last 100), debounce 80 ms
  C->>H: GET /api/v1/workspace (authoritative state)
```

## Client freshness strategy

```mermaid
flowchart LR
  conn{"Socket connected?"} -- yes --> slow["poll /workspace every 15 s<br/>+ immediate refresh on each event"]
  conn -- no --> fast["poll /workspace every 2 s"]
  reconnect["connect / disconnect event"] --> refreshNow["refresh() immediately"]
```

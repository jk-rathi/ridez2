# State machines

[← Back to index](../README.md)

## Ride status (`rides.status`)

Allowed values are enforced by the `valid_ride_state` CHECK constraint. Transitions are implemented in `backend/app/ride_service.py` (`book`, `accept`, `move`) and `backend/app/matching.py` (`advance`). Every transition except the `NO_DRIVER_FOUND` timeout is a **conditional UPDATE** (`ride_repository.transition` / `ride_repository.assign`) so that only one concurrent request can win.

```mermaid
stateDiagram-v2
  [*] --> SEARCHING : POST /rides (book)
  SEARCHING --> SEARCHING : round expires, radius += 500 m (matching.advance)
  SEARCHING --> ASSIGNED : driver accepts (ride_repository.assign)
  SEARCHING --> NO_DRIVER_FOUND : final round expires at MATCH_MAX_RADIUS_M
  SEARCHING --> CANCELLED : rider cancels
  ASSIGNED --> ARRIVING : driver 'depart'
  ARRIVING --> WAITING : driver 'arrive'
  WAITING --> IN_PROGRESS : driver 'start' + correct OTP
  IN_PROGRESS --> COMPLETED : driver 'complete'
  ASSIGNED --> CANCELLED : rider or driver, reason required
  ARRIVING --> CANCELLED : rider or driver, reason required
  WAITING --> CANCELLED : rider or driver, reason required
  COMPLETED --> [*]
  CANCELLED --> [*]
  NO_DRIVER_FOUND --> [*]
```

`IN_PROGRESS` rides **cannot be cancelled** (HTTP 409). There is no incident/abort workflow for an in-progress trip.

## Invitation status (`ride_invitations.status`)

No CHECK constraint; values are set in code.

```mermaid
stateDiagram-v2
  [*] --> PENDING : matching.invite()
  PENDING --> ACCEPTED : this driver accepts
  PENDING --> CLOSED : another driver accepts / ride cancelled / driver logs out or is suspended
  PENDING --> REJECTED : driver rejects
  PENDING --> EXPIRED : round deadline passes (matching.advance)
  PENDING --> OFFLINE : driver sets available=false
```

## Driver operational state (derived, not a single column)

There is **no driver-state enum** in the database. A driver's operational state is derived from four sources: `users.status`, `driver_presence.available`, `driver_presence.resume_available`, `active_rides`, and the freshness of `driver_locations`.

```mermaid
stateDiagram-v2
  [*] --> Pending : register(role=driver) → users.status='pending'
  Pending --> Offline : admin approve → status='active'
  Offline --> Available : POST /driver/availability {available:true} + fresh GPS
  Available --> Offline : available:false / logout / suspend / GPS permission revoked
  Available --> Invisible : location older than 90 s (fresh=false) — excluded from matching
  Invisible --> Available : fresh PUT /driver/location
  Available --> OnTrip : accepts invitation → available=false, active_rides row
  OnTrip --> Available : complete AND resume_available AND fresh GPS AND status active
  OnTrip --> Offline : complete with resume_available=false / stale GPS / suspended
  OnTrip --> Offline : ride cancelled (driver always left offline)
  Offline --> Suspended : admin suspend (status='suspended')
  Available --> Suspended : admin suspend
  OnTrip --> OnTrip : admin suspend — trip preserved, can still finish
  Suspended --> Offline : admin reinstate
```

## Ride payment (`ride_payments`)

```mermaid
stateDiagram-v2
  [*] --> PENDING_no_method : trip completes (payment_service.record_completion)
  PENDING_no_method --> PENDING_CASH : rider chooses CASH
  PENDING_no_method --> PENDING_ONLINE : rider chooses ONLINE
  PENDING_CASH --> PENDING_ONLINE : rider switches
  PENDING_ONLINE --> PENDING_CASH : rider switches
  PENDING_no_method --> CONFIRMED_CASH : driver 'confirm-cash'
  PENDING_CASH --> CONFIRMED_CASH : driver 'confirm-cash'
  PENDING_ONLINE --> CONFIRMED_CASH : driver 'confirm-cash'
  PENDING_no_method --> CONFIRMED_ONLINE : mock QR SUCCESS
  PENDING_CASH --> CONFIRMED_ONLINE : mock QR SUCCESS
  PENDING_ONLINE --> CONFIRMED_ONLINE : mock QR SUCCESS
  CONFIRMED_CASH --> [*]
  CONFIRMED_ONLINE --> [*]
```

`CONFIRMED` is final. The first confirmation wins because `payment_service.confirm` updates only `WHERE status='PENDING'`. A third method, `UNRECORDED`, only exists for rides completed **before** payment tracking was added (back-filled by migration `7ba01cddd40c`).

## Mock QR payment (`mock_payments`)

```mermaid
stateDiagram-v2
  [*] --> PENDING : rider POST /rides/{id}/test-payment
  PENDING --> FAILED : QR page 'Simulate failed'
  FAILED --> PENDING : 'Simulate pending'
  PENDING --> SUCCESS : 'Simulate success' → ride_payments CONFIRMED/ONLINE
  FAILED --> SUCCESS
  SUCCESS --> [*] : sticky — later requests never downgrade
```

## Auth session (`auth_sessions` + `refresh_tokens`)

```mermaid
stateDiagram-v2
  [*] --> Active : login → session + first refresh token
  Active --> Active : refresh → old token used_at set, new token issued
  Active --> Revoked : logout / logout-all / refresh-token replay / user disabled
  Active --> Expired : expires_at (30 days) passes
  Revoked --> [*]
  Expired --> [*]
```

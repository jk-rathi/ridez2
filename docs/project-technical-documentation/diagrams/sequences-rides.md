# Ride sequence diagrams

[← Back to index](../README.md) · Details: [09 — Features](../09-feature-by-feature-explanation.md), [10 — Data flow](../10-complete-data-flow.md)

## Driver goes available and streams GPS

```mermaid
sequenceDiagram
  autonumber
  actor D as Driver
  participant RW as RideWorkspace.changeDriverAvailability
  participant GP as useDriverLocation.getPosition
  participant API as POST /driver/availability
  participant RS as ride_service.availability
  participant LS as location_service.update
  participant DB as DB
  D->>RW: click "Go available"
  RW->>GP: navigator.geolocation (high accuracy, then low-accuracy retry)
  GP-->>RW: {latitude, longitude, accuracy_m, recorded_at}
  RW->>API: {available:true, ...position}
  API->>RS: availability(user, data)
  RS->>RS: expire() → matching.advance()
  RS->>DB: lock_active_driver: UPDATE users SET status_revision=status_revision WHERE status='active'
  RS->>LS: update(user, data, initializing=True)
  LS->>LS: validate lat/lng/accuracy ≤200 m, recorded_at within (now-90 s, now+15 s]
  LS->>DB: upsert driver_locations (fresh=true) + outbox event
  RS->>DB: driver_presence.available = true, resume_available = true
  RS-->>RW: {available:true, resume_available:true, active_trip:false}
  loop every 30 s (10 s on a trip) while tab open
    GP->>DB: PUT /driver/location → location_service.update (movement ≤ 200 km/h + accuracy + 100 m)
  end
```

## Fare quote

```mermaid
sequenceDiagram
  autonumber
  actor R as Rider
  participant BP as BookingPanel.submit
  participant Q as POST /fares/quotes (ride_routes.quote)
  participant RS as ride_service.quote
  participant RP as route_provider.compute
  participant G as Google Routes API
  participant FS as fare_service.calculate
  participant DB as DB
  R->>BP: choose pickup/destination (AddressSearch or map click), "Get fare estimate"
  BP->>Q: {pickup, destination, pickup_lat, pickup_lng, destination_lat?, destination_lng?}
  Q->>Q: per-rider limiter: 10 quotes / 60 s
  Q->>RS: quote(user, body)
  RS->>RS: text() + coordinate() validation, pickup ≠ destination
  RS->>RS: expire() → matching.advance()
  RS->>RP: compute(pickup, destination, labels)
  alt ROUTE_PROVIDER = simulator
    RP->>RP: SHA-256(labels) → distance 2–20 km, duration 3 min/km (≥5 min)
  else google
    RP->>G: POST computeRoutes (TRAFFIC_AWARE, field mask)
    G-->>RP: distanceMeters, duration, staticDuration, polyline
  end
  RS->>FS: calculate(route, pickup)
  FS->>DB: latest fare_policies (or DEFAULT_POLICY)
  FS->>FS: base + km·rate + min·rate, minimum, highest surge (zone/traffic/demand) capped
  RS->>DB: INSERT fare_quotes (expires +5 min)
  RS-->>BP: 201 {quote: {...itemized, polyline}}
```

## Booking and matching round 1

```mermaid
sequenceDiagram
  autonumber
  participant BP as BookingPanel
  participant B as POST /rides
  participant RS as ride_service.book
  participant M as matching.invite
  participant DB as DB
  BP->>B: {quote_id}
  B->>RS: book(user, data)
  RS->>RS: expire(), quote exists & owned
  RS->>DB: ride_for_quote(quote_id) → if exists return it (idempotent)
  RS->>RS: quote not expired, provider unchanged, has pickup coords
  RS->>DB: active_rides.get(rider) → 409 if busy
  RS->>DB: INSERT rides (SEARCHING, round 1, radius 500, expires now+30 s)
  RS->>DB: INSERT active_rides (rider)
  RS->>M: invite(ride, requested_at)
  M->>DB: INSERT ride_match_rounds (round 1)
  M->>DB: eligible_drivers(): available, active, fresh GPS, not busy
  loop each candidate within radius_m (haversine)
    M->>DB: lock_active_driver(require_available=True)
    M->>DB: INSERT ride_invitations PENDING
  end
  RS->>DB: notify_ride → outbox events (rider, invitees, admins)
  RS->>DB: COMMIT (IntegrityError → return existing ride or 409)
```

## Round expiry (background worker or any request)

```mermaid
sequenceDiagram
  participant W as realtime.tick / any request's expire()
  participant A as matching.advance
  participant DB as DB
  W->>A: advance()
  loop up to MATCH_MAX_RADIUS_M/500+1 passes
    A->>DB: expired_searches(now): SEARCHING and expires_at ≤ now
    A->>DB: expire_round: UPDATE rides SET round_no+1 WHERE round_no,expires_at unchanged (claim)
    A->>DB: old round outcome = EXPIRED, PENDING invitations → EXPIRED
    alt radius ≥ max
      A->>DB: status = NO_DRIVER_FOUND, release active claim
    else
      A->>DB: radius += 500, expires_at = old deadline + 30 s
      A->>A: invite(ride) — only drivers not previously invited
    end
    A->>DB: notify_ride, COMMIT
  end
  A->>DB: mark driver_locations older than 90 s as fresh=false (+ notify)
```

## Driver accepts

```mermaid
sequenceDiagram
  autonumber
  participant RW as RideWorkspace (driver)
  participant AC as POST /rides/{id}/accept
  participant RS as ride_service.accept
  participant DB as DB
  RW->>AC: perform('/rides/{id}/accept')
  AC->>RS: accept(user, ride_id)
  RS->>RS: expire(), invitation exists (404)
  RS->>RS: already this driver's ride → return it (idempotent)
  RS->>DB: driver has active claim → 409
  RS->>RS: active + available (403), fresh location (409), invitation PENDING & ride SEARCHING & not expired (409)
  RS->>DB: lock_active_driver
  RS->>DB: assign(): UPDATE rides SET ASSIGNED, driver_id, vehicle snapshot WHERE SEARCHING AND unexpired AND valid invitation AND driver eligible
  alt rowcount 0
    RS-->>RW: 409 'Another driver has already accepted this ride'
  else won
    RS->>DB: INSERT active_rides (driver) — PK prevents double booking
    RS->>DB: other invitations → CLOSED, this → ACCEPTED
    RS->>DB: driver_presence.available = false, round outcome ASSIGNED
    RS->>DB: notify_ride, COMMIT
  end
```

## Trip progression and OTP

```mermaid
sequenceDiagram
  participant D as Driver RideCard
  participant MV as POST /rides/{id}/{action} → ride_service.move
  participant OTP as services.verify_trip_otp
  participant DB as DB
  D->>MV: depart  (ASSIGNED → ARRIVING)
  D->>MV: arrive  (ARRIVING → WAITING)
  D->>MV: start {otp}  (WAITING → IN_PROGRESS)
  MV->>OTP: 5 failures / driver / minute → 429, HMAC(USER_CODE_SECRET, 'trip-otp:v2:'+ride.id) mod 10^6
  D->>MV: complete  (IN_PROGRESS → COMPLETED)
  MV->>DB: transition(): UPDATE rides SET status=new WHERE id AND status=old
  Note over MV,DB: complete also → revenue_service.allocate, payment_service.record_completion,<br/>release claims, decide driver auto-availability
```

## Cancellation

```mermaid
sequenceDiagram
  participant U as Rider / assigned driver
  participant C as CancelRideControl.submit
  participant MV as ride_service.move(action='cancel')
  participant DB as DB
  U->>C: choose reason (+ notes), confirm
  C->>MV: POST /rides/{id}/cancel {reason}
  MV->>MV: only rider of ride or assigned driver (403)
  MV->>MV: already CANCELLED → return record (idempotent)
  MV->>MV: status must be SEARCHING/ASSIGNED/ARRIVING/WAITING (409)
  MV->>MV: reason 1–300 chars (optional only for SEARCHING, defaults 'Rider cancelled the search')
  MV->>DB: transition(→ CANCELLED, cancelled_at, cancelled_by, reason)
  MV->>DB: invitations → CLOSED, driver available=false, resume_available=false
  MV->>DB: release active claims, close round if SEARCHING, notify, COMMIT
```

## Live trip map

```mermaid
sequenceDiagram
  participant H as useTripRoute (TripRouteMap.jsx)
  participant TM as GET /rides/{id}/map → trip_map_service.trip_map
  participant C as cached_route (in-memory, 60 s)
  participant G as Google Routes
  loop every refresh_after_seconds (10 s) or 15 s after error
    H->>TM: GET
    TM->>TM: rider/driver only, ride active, Google quote, Google mode
    TM->>TM: phase: approach (ASSIGNED/ARRIVING) | overview (SEARCHING/WAITING) | in_progress
    TM->>TM: origin = fresh driver GPS or pickup, target = pickup (approach) or destination
    TM->>C: key (ride, phase, source, target, at_destination)
    C->>G: compute only if no cached entry (concurrent callers share one Future)
    TM->>TM: re-read ride, 409 if phase/source changed during the Google call
    TM-->>H: polyline, distance_m, duration_seconds, driver_position, refresh_after_seconds:10
  end
```

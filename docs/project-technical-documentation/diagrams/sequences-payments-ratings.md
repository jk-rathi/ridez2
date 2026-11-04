# Completion, payment and rating sequence diagrams

[← Back to index](../README.md)

## Trip completion

```mermaid
sequenceDiagram
  autonumber
  participant D as Driver RideCard
  participant MV as ride_service.move('complete')
  participant RV as revenue_service.allocate
  participant PS as payment_service.record_completion
  participant DB as DB
  D->>MV: POST /rides/{id}/complete (after window.confirm)
  MV->>DB: lock_driver (serialize with suspension/offline)
  MV->>DB: transition IN_PROGRESS → COMPLETED, completed_at
  MV->>RV: allocate(ride, quote, driver, completed_at)
  RV->>DB: active split at completed_at (default 85/15)
  RV->>DB: INSERT revenue_ledger (driver_amount rounded half-up, company = remainder)
  MV->>PS: record_completion
  PS->>DB: INSERT ride_payments PENDING amount = quote.total
  MV->>DB: DELETE active_rides for ride
  MV->>MV: eligible = active AND resume_available AND fresh GPS AND bookings enabled
  MV->>DB: driver_presence.available = eligible, notify, COMMIT
```

A retried `complete` returns the existing ride: `ride.status == new` short-circuits before any writes. The `revenue_ledger` and `ride_payments` primary keys (`ride_id`) are a second line of defence against double allocation.

## Rider pays in cash

```mermaid
sequenceDiagram
  participant RP as PaymentPrompt (TestPayment.jsx)
  participant PM as POST /rides/{id}/payment-method
  participant DC as DriverCollectCard (PaymentStatus.jsx)
  participant CC as POST /rides/{id}/confirm-cash
  participant DB as ride_payments
  RP->>PM: {method:'CASH'}
  PM->>DB: UPDATE method='CASH' WHERE status='PENDING', notify rider+driver
  Note over DC: Driver overview lists every COMPLETED ride with payment PENDING
  DC->>CC: "Cash received" (window.confirm)
  CC->>DB: UPDATE status='CONFIRMED', method='CASH', confirmed_by WHERE status='PENDING'
  alt rowcount 0 and method ONLINE
    CC-->>DC: 409 'The rider has already paid online'
  else
    CC-->>DC: payment {status:'CONFIRMED', method:'CASH'}
  end
  Note over RP: workspace refresh → PaymentSuccess + RatingForm
```

## Rider pays "online" (mock QR, test only)

```mermaid
sequenceDiagram
  autonumber
  participant RP as PaymentPrompt / TestPaymentCard
  participant TP as POST /rides/{id}/test-payment
  participant Phone as Phone camera → /test-payment/:token
  participant TPP as TestPaymentPage
  participant SIM as POST /test-payments/{token}
  participant DB as DB
  RP->>TP: generate()
  TP->>TP: TEST_PAYMENTS_ENABLED (else 404), rider owns ride, COMPLETED, not paid by other method
  TP->>DB: INSERT mock_payments PENDING (idempotent on IntegrityError)
  TP-->>RP: path '/test-payment/' + itsdangerous token(ride_id, salt 'mock-qr-payment-v1'), expires_in 900
  RP->>RP: QRCode.toDataURL(absolute URL)
  Phone->>TPP: open URL (no login needed — bearer capability)
  TPP->>SIM: GET → amount + status
  TPP->>SIM: POST {status:'SUCCESS'|'FAILED'|'PENDING'}
  SIM->>DB: UPDATE mock_payments SET status WHERE status != 'SUCCESS' AND status != new
  alt changed and SUCCESS
    SIM->>DB: payment_service.confirm(ride,'ONLINE') — first confirmation wins
  end
  SIM->>DB: notify rider + driver, COMMIT
  Note over RP: socket push → workspace refresh → success animation
```

## Two-way rating

```mermaid
sequenceDiagram
  participant RF as RatingForm (Rating.jsx)
  participant RT as POST /rides/{id}/rating
  participant RS as rating_service.submit
  participant DB as ride_ratings
  RF->>RT: {stars, tags[], comment?}
  RT->>RT: role must be rider or driver (403)
  RT->>RS: submit(user, ride_id, data)
  RS->>RS: participant of ride (404), ride COMPLETED (409)
  RS->>RS: stars int 1–5, ≤5 tags from TAGS[role], comment ≤300
  RS->>DB: INSERT (ride_id, rater_role) …
  alt IntegrityError (already rated)
    RS->>DB: existing.stars == stars → return existing, else 409
  end
  RS-->>RF: rating (tags list, comment, created_at)
```

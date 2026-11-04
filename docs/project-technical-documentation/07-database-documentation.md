# 07 — Database documentation

[← Back to index](README.md) · Next: [08 — Authentication and security →](08-authentication-and-security.md)

Source of truth: `backend/app/models.py` and `backend/migrations/versions/*.py`. ERD: [diagrams/erd.md](diagrams/erd.md).

## 1. Database engines

| Context | URL | Notes |
| --- | --- | --- |
| Local dev | `sqlite:///ridez.db` (default when `APP_ENV=development` and no `DATABASE_URL`) | Relative path resolved by Flask-SQLAlchemy into the instance folder **(inferred)** |
| Tests | `sqlite://` (memory) or `sqlite:///<tmp>/…` | `db.create_all()` (not migrations) in fixtures |
| Render | `sqlite:////var/data/ridez.db` | Persistent disk; single instance |
| Intended | `mssql+pyodbc://…?driver=ODBC+Driver+18+for+SQL+Server` | **Not validated**; driver not in image |

Engine option: `pool_pre_ping=True`. All migrations use `batch_alter_table`, which lets Alembic rebuild tables on SQLite (SQLite cannot ALTER constraints).

## 2. Conventions

- **IDs**: `users.id` is an auto-increment integer. Rides, quotes, sessions, outbox events and admin audit rows use `String(36)` UUID4 strings generated in Python (`str(uuid4())`).
- **Timestamps**: naive UTC `DateTime` (except `users.created_at`, `DateTime(timezone=True)`).
- **Money**: `Numeric(10,2)` (mock payments `Numeric(12,2)`), percentages `Numeric(5,2)`.
- **Enums** are strings guarded by CHECK constraints where defined.
- **No ORM relationships** (`relationship()`) are declared; joins are explicit in queries.
- **No ON DELETE cascades**; the application never deletes users, rides or quotes. The only deletes are `active_rides` (claim release) and old delivered `outbox_events`.

## 3. Tables

Legend: **PK** primary key, **FK** foreign key, **UQ** unique, **IX** index, **NN** not null.

### 3.1 `users` — accounts (`User`)

| Column | Type | NN | Default | Key | Notes |
| --- | --- | --- | --- | --- | --- |
| `id` | Integer | ✓ | autoincrement | PK | |
| `name` | String(100) | ✓ | | | trimmed, 1–100 |
| `mobile` | String(20) | ✓ | | UQ | E.164 (`+919876543210`) |
| `password_hash` | String(512) | ✓ | | | Werkzeug hash string |
| `user_code` | String(40) | ✓ | | UQ | `RID-`/`DRV-`/`ADM-` + base32 HMAC prefix |
| `role` | String(16) | ✓ | | | CHECK `valid_user_role`: rider, driver, admin |
| `status` | String(16) | ✓ | `'active'` | | CHECK `valid_user_status`: active, pending, disabled, suspended; suspended only if role = driver |
| `status_revision` | Integer | ✓ | 0 (server default `'0'`) | | Optimistic version for admin reviews; also target of no-op lock UPDATEs |
| `created_at` | DateTime(tz) | ✓ | now UTC | | |

**Create:** `services.register` (API/CLI/bootstrap). **Read:** login, authenticate (every request), ride JSON, admin lists. **Update:** `status`/`status_revision` by `admin_service.change_driver_status`; no-op `status_revision = status_revision` locks by `ride_repository.lock_*` and vehicle save. **Delete:** never.

### 3.2 `driver_presence` — online flag (`DriverPresence`)

| Column | Type | NN | Default | Key |
| --- | --- | --- | --- | --- |
| `driver_id` | Integer | ✓ | | PK, FK users.id |
| `available` | Boolean | ✓ | False | |
| `resume_available` | Boolean | ✓ | True (server `true`) | |

`available` = currently eligible to receive invitations. `resume_available` = driver's choice to stay available after the current trip (added by `e83a01cf742d`). Written by `ride_repository.set_available`, `session_service.stop_requests`.

### 3.3 `driver_locations` — latest GPS fix (`DriverLocation`)

| Column | Type | NN | Key | Notes |
| --- | --- | --- | --- | --- |
| `driver_id` | Integer | ✓ | PK, FK | one row per driver (no history) |
| `latitude`, `longitude` | Float | ✓ | | |
| `accuracy_m` | Float | ✓ | | 0–200 |
| `recorded_at` | DateTime | ✓ | | device capture time |
| `updated_at` | DateTime | ✓ | IX | server receipt time |
| `fresh` | Boolean | ✓ | | default True; set False by `matching.advance` after 90 s |

### 3.4 `driver_vehicles` — admin-reviewed car (`DriverVehicle`)

| Column | Type | NN | Key |
| --- | --- | --- | --- |
| `driver_id` | Integer | ✓ | PK, FK |
| `registration` | String(20) | ✓ | |
| `model` | String(80) | ✓ | |
| `color` | String(40) | ✓ | |
| `version` | Integer | ✓ | optimistic version (1 on first save) |

### 3.5 `fare_quotes` — immutable price snapshots (`FareQuote`)

| Column | Type | NN | Default | Notes |
| --- | --- | --- | --- | --- |
| `id` | String(36) | ✓ | | PK UUID |
| `rider_id` | Integer | ✓ | | FK users |
| `pickup`, `destination` | String(160) | ✓ | | labels |
| `distance_km` | Numeric(10,2) | ✓ | | |
| `duration_min` | Integer | ✓ | | ceil(seconds/60) |
| `base`, `distance_fare`, `time_fare`, `total` | Numeric(10,2) | ✓ | | |
| `expires_at` | DateTime | ✓ | | created + 5 min |
| `pickup_lat`, `pickup_lng` | Float | | | required by current code; nullable for legacy rows |
| `destination_lat`, `destination_lng` | Float | | | null in simulator mode unless supplied |
| `provider` | String(16) | ✓ | `'simulator'` | `google` or `simulator` |
| `distance_m`, `duration_seconds`, `baseline_seconds` | Integer | | | baseline = Google `staticDuration` |
| `subtotal`, `minimum_adjustment` | Numeric(10,2) | | | |
| `surge_multiplier` | Numeric(5,2) | ✓ | 1 | |
| `surge_amount` | Numeric(10,2) | ✓ | 0 | |
| `surge_reason` | String(500) | ✓ | `'No surge'` | |
| `fare_rule_version` | Integer | ✓ | 0 | `fare_policies.version` used (0 = defaults) |
| `rate_snapshot` | Text | | | JSON: rates, cap, timezone, applied `zone_ids`, `traffic_ratio`, `demand_ratio` |

Never updated after insert. Polyline is **not** stored.

### 3.6 `fare_policies` — versioned fare rules (`FarePolicy`)

| Column | Type | NN | Key |
| --- | --- | --- | --- |
| `version` | Integer | ✓ | PK (manual, no autoincrement) |
| `settings` | Text | ✓ | JSON policy (see `fare_service.DEFAULT_POLICY` for keys) |
| `updated_by` | Integer | ✓ | FK users |
| `reason` | String(300) | ✓ | |
| `created_at` | DateTime | ✓ | |

Append-only. Latest version = current policy. No rows → `DEFAULT_POLICY` with version 0.

### 3.7 `rides` — trips (`Ride`)

| Column | Type | NN | Default | Key / notes |
| --- | --- | --- | --- | --- |
| `id` | String(36) | ✓ | | PK UUID |
| `rider_id` | Integer | ✓ | | FK users |
| `driver_id` | Integer | | | FK users; set on assignment |
| `quote_id` | String(36) | ✓ | | FK fare_quotes, **UQ** (booking idempotency) |
| `status` | String(24) | ✓ | | CHECK `valid_ride_state` (8 values) |
| `requested_at` | DateTime | ✓ | | |
| `expires_at` | DateTime | ✓ | | **current matching round deadline** (meaningless after assignment) |
| `completed_at` | DateTime | | | |
| `cancelled_at` | DateTime | | | |
| `cancelled_by` | Integer | | | FK users (`fk_rides_cancelled_by_users`) |
| `cancellation_reason` | String(300) | | | |
| `vehicle_registration` | String(20) | | | snapshot at acceptance |
| `vehicle_model` | String(80) | | | snapshot |
| `vehicle_color` | String(40) | | | snapshot |
| `round_no` | Integer | ✓ | 1 | |
| `radius_m` | Integer | ✓ | 500 | |

No index on `rider_id`, `driver_id` or `status` beyond the PK/UQ (see [18](18-problems-and-improvements.md)).

### 3.8 `active_rides` — participation claims (`ActiveRide`)

| Column | Type | NN | Key |
| --- | --- | --- | --- |
| `user_id` | Integer | ✓ | **PK**, FK users |
| `ride_id` | String(36) | ✓ | FK rides |

Rows exist for the rider from booking until completion/cancellation/no-driver, and for the driver from acceptance until completion/cancellation. **PK on `user_id` = a user can be in at most one active ride.** Deleted by `ride_repository.release(ride_id)`.

### 3.9 `ride_invitations` — offers (`Invitation`)

| Column | Type | NN | Default | Key |
| --- | --- | --- | --- | --- |
| `ride_id` | String(36) | ✓ | | PK, FK |
| `driver_id` | Integer | ✓ | | PK, FK |
| `status` | String(16) | ✓ | `'PENDING'` | PENDING, ACCEPTED, REJECTED, EXPIRED, CLOSED, OFFLINE (no CHECK) |
| `round_no` | Integer | ✓ | 1 | round in which the invite was sent |
| `expires_at` | DateTime | | | = round deadline |

Composite PK prevents re-inviting the same driver for the same ride.

### 3.10 `ride_match_rounds` — round history (`MatchRound`)

| Column | Type | NN | Key |
| --- | --- | --- | --- |
| `ride_id` | String(36) | ✓ | PK, FK |
| `round_no` | Integer | ✓ | PK |
| `radius_m` | Integer | ✓ | |
| `started_at` | DateTime | ✓ | |
| `expires_at` | DateTime | ✓ | |
| `outcome` | String(24) | ✓ | SEARCHING (default), EXPIRED, ASSIGNED, CANCELLED |

Audit/history only; matching logic reads `rides.round_no/expires_at`, not this table. (The final round of a NO_DRIVER_FOUND ride is marked EXPIRED.)

### 3.11 `outbox_events` — notification queue (`OutboxEvent`)

| Column | Type | NN | Key | Notes |
| --- | --- | --- | --- | --- |
| `id` | String(36) | ✓ | PK | event_id sent to clients |
| `user_id` | Integer | | FK | NULL → `admins` room |
| `created_at` | DateTime | ✓ | | ordering |
| `delivered_at` | DateTime | | IX | NULL = pending |

Written in the same transaction as the business change (transactional outbox). Delivered rows are deleted after 7 days.

### 3.12 `revenue_ledger` — allocations (`RevenueLedger`)

| Column | Type | NN | Default | Key |
| --- | --- | --- | --- | --- |
| `ride_id` | String(36) | ✓ | | **PK**, FK rides (one allocation per ride) |
| `driver_id` | Integer | ✓ | | FK users |
| `eligible_fare` | Numeric(10,2) | ✓ | | = quote total |
| `driver_pct`, `company_pct` | Numeric(5,2) | ✓ | | |
| `driver_amount`, `company_amount` | Numeric(10,2) | ✓ | | sum = eligible_fare |
| `share_version` | Integer | ✓ | 0 | revenue setting version used |
| `created_at` | DateTime | | | = completed_at |

### 3.13 `revenue_share_settings` — split versions (`RevenueShareSetting`)

| Column | Type | NN | Key / constraint |
| --- | --- | --- | --- |
| `version` | Integer | ✓ | PK (manual) |
| `driver_pct`, `company_pct` | Numeric(5,2) | ✓ | CHECK `valid_revenue_split`: each 0–100 and sum = 100 |
| `previous_driver_pct`, `previous_company_pct` | Numeric(5,2) | ✓ | split active when saved |
| `effective_from` | DateTime | ✓ | IX |
| `created_at` | DateTime | ✓ | |
| `updated_by` | Integer | ✓ | FK users |
| `reason` | String(300) | ✓ | |

### 3.14 `admin_audit` — driver review log (`AdminAudit`)

| Column | Type | NN | Notes |
| --- | --- | --- | --- |
| `id` | String(36) | ✓ | PK UUID |
| `admin_id` | Integer | ✓ | FK users |
| `driver_id` | Integer | ✓ | FK users |
| `action` | String(40) | ✓ | `driver.approved`, `driver.suspended`, `driver.reinstated`, `driver.vehicle.updated` |
| `reason` | String(300) | ✓ | shown to driver for suspensions |
| `created_at` | DateTime | ✓ | |
| `before_status`, `after_status` | String(16) | | status changes |
| `status_revision` | Integer | | revision after change (used to find current suspension reason and detect retries) |
| `details` | Text | | JSON `{before, after}` for vehicle edits |

### 3.15 `auth_sessions` — server sessions (`AuthSession`)

| Column | Type | NN | Key |
| --- | --- | --- | --- |
| `id` | String(36) | ✓ | PK (JWT `sid`) |
| `user_id` | Integer | ✓ | FK, IX |
| `created_at`, `expires_at` | DateTime | ✓ | 30-day absolute lifetime |
| `revoked_at` | DateTime | | |

### 3.16 `refresh_tokens` — rotating credentials (`RefreshToken`)

| Column | Type | NN | Key |
| --- | --- | --- | --- |
| `token_hash` | String(64) | ✓ | PK (SHA-256 hex) |
| `session_id` | String(36) | ✓ | FK auth_sessions, IX |
| `created_at` | DateTime | ✓ | |
| `used_at` | DateTime | | set on rotation (single use) |

Old rows are never deleted (see [18](18-problems-and-improvements.md)).

### 3.17 `ride_payments` — real payment state (`RidePayment`)

| Column | Type | NN | Default | Constraint |
| --- | --- | --- | --- | --- |
| `ride_id` | String(36) | ✓ | | PK, FK |
| `method` | String(16) | | | CHECK `valid_ride_payment_method`: NULL or CASH/ONLINE/UNRECORDED |
| `status` | String(16) | ✓ | `'PENDING'` | CHECK `valid_ride_payment_status`: PENDING/CONFIRMED |
| `amount` | Numeric(10,2) | ✓ | | = quote total |
| `updated_at` | DateTime | ✓ | | |
| `confirmed_at` | DateTime | | | |
| `confirmed_by` | Integer | | | FK users (driver for cash; NULL for online) |
| | | | | CHECK `confirmed_ride_payment_complete`: status = PENDING OR (method and confirmed_at not null) |

### 3.18 `mock_payments` — test QR state (`MockPayment`)

| Column | Type | NN | Default | Constraint |
| --- | --- | --- | --- | --- |
| `ride_id` | String(36) | ✓ | | PK, FK |
| `amount` | Numeric(12,2) | ✓ | | |
| `status` | String(16) | ✓ | `'PENDING'` | CHECK PENDING/FAILED/SUCCESS |

### 3.19 `ride_ratings` — two-way ratings (`RideRating`)

| Column | Type | NN | Key / constraint |
| --- | --- | --- | --- |
| `ride_id` | String(36) | ✓ | PK, FK |
| `rater_role` | String(8) | ✓ | PK; CHECK rider/driver |
| `rater_id` | Integer | ✓ | FK users |
| `ratee_id` | Integer | ✓ | FK users, IX `ix_ride_ratings_ratee_id` (for averages) |
| `stars` | Integer | ✓ | CHECK 1–5 |
| `tags` | String(200) | | pipe-joined (`\|`) |
| `comment` | String(300) | | admin-only visibility |
| `created_at` | DateTime | ✓ | |

Plus Alembic's own `alembic_version` table (read by `/ready`).

## 4. Relationships summary

| From | To | Cardinality | Enforced by |
| --- | --- | --- | --- |
| users (rider) | fare_quotes | 1 : N | FK |
| fare_quotes | rides | 1 : 0..1 | FK + UQ `rides.quote_id` |
| users | rides (rider / driver / cancelled_by) | 1 : N | FKs |
| rides | active_rides | 1 : 0..2 | FK; PK on user |
| rides | ride_invitations | 1 : N | composite PK |
| rides | ride_match_rounds | 1 : N | composite PK |
| rides | revenue_ledger, ride_payments, mock_payments | 1 : 0..1 | PK = ride_id |
| rides | ride_ratings | 1 : 0..2 | PK (ride_id, rater_role) |
| users (driver) | driver_presence, driver_locations, driver_vehicles | 1 : 0..1 | PK = driver_id |
| users | auth_sessions → refresh_tokens | 1 : N : N | FKs |
| users (admin) | fare_policies, revenue_share_settings, admin_audit | 1 : N | FKs |

## 5. Important queries

| Purpose | Query (simplified) | File |
| --- | --- | --- |
| Eligible drivers | `SELECT driver_presence JOIN users JOIN driver_locations WHERE available AND users.status='active' AND fresh AND recorded_at>cutoff AND updated_at>cutoff AND driver_id NOT IN (SELECT user_id FROM active_rides)` | `ride_repository.eligible_drivers` |
| Atomic assignment | `UPDATE rides SET status='ASSIGNED', driver_id, vehicle_* WHERE id=? AND status='SEARCHING' AND expires_at>now AND id IN (valid invitation) AND EXISTS(eligible driver)` | `ride_repository.assign` |
| State transition | `UPDATE rides SET status=:new … WHERE id=? AND status=:old` | `ride_repository.transition` |
| Round claim | `UPDATE rides SET round_no=round_no+1 WHERE id AND status='SEARCHING' AND round_no=? AND expires_at=? AND expires_at<=now` | `ride_repository.expire_round` |
| Driver row lock | `UPDATE users SET status_revision=status_revision WHERE id=? AND role='driver' [AND status='active'] [AND EXISTS available]` | `ride_repository.lock_active_driver/lock_driver` |
| Refresh single-use | `UPDATE refresh_tokens SET used_at=now WHERE token_hash=? AND used_at IS NULL` | `session_service.refresh` |
| Payment first-wins | `UPDATE ride_payments SET status='CONFIRMED', method … WHERE ride_id=? AND status='PENDING'` | `payment_service.confirm` |
| Mock no-downgrade | `UPDATE mock_payments SET status=? WHERE ride_id=? AND status!='SUCCESS' AND status!=?` | `test_payment_routes.simulate_test_payment` |
| Active revenue split | `SELECT … WHERE effective_from<=at ORDER BY effective_from DESC, version DESC LIMIT 1` | `revenue_service.active` |
| Rating summary | `SELECT AVG(stars), COUNT(*) FROM ride_ratings WHERE ratee_id=?` | `rating_service.summary` |
| Audit feed | `UNION ALL` of three tables → JOIN users → ILIKE → ORDER BY created_at DESC, category, id DESC LIMIT 20 OFFSET … | `admin_service.audit` |
| Metrics | `SELECT status, COUNT(*) FROM rides GROUP BY status`, counts and sums | `admin_service.metrics` |

## 6. Transactions and consistency

- One SQLAlchemy session per request/app context (Flask-SQLAlchemy scoped session). Services commit explicitly; uncommitted work is rolled back at teardown.
- Multi-table operations (booking, acceptance, completion, cancellation, review) run in **one transaction** including their outbox rows.
- Race safety comes from conditional UPDATEs, uniqueness constraints and catching `IntegrityError`, not from `SELECT … FOR UPDATE`.
- Status/business invariants enforced in the database: ride status values, user role/status combination, revenue split sum, payment status/method completeness, rating stars range and role.
- Invariants enforced only in code: invitation status values, match round outcomes, the ride state machine order (enforced through `transition(old,new)`), vehicle registration format.

## 7. Migrations

Linear chain (oldest → newest). Apply with `flask --app run db upgrade` (dev) or `flask --app wsgi db upgrade` (prod, done automatically by `deploy/start.sh`).

| # | Revision | Adds |
| --- | --- | --- |
| 1 | `15e7a3910568` | `users` with role/status CHECKs, UQ mobile and user_code |
| 2 | `4b12d0134b2f` | `admin_audit`, `driver_presence`, `fare_quotes`, `rides` (state CHECK, UQ quote_id), `active_rides`, `revenue_ledger`, `ride_invitations` |
| 3 | `61c1900fe70b` | `driver_locations` (+IX), `outbox_events` (+IX), `ride_match_rounds`; `fare_quotes.pickup_lat/lng`; `ride_invitations.round_no/expires_at`; `rides.round_no/radius_m` |
| 4 | `11ca7c6daf35` | `fare_policies`; quote destination coords, provider, route metrics, subtotal, minimum adjustment, surge columns, `fare_rule_version`, `rate_snapshot` |
| 5 | `5854899d25f7` | `revenue_share_settings` (+IX effective_from); `revenue_ledger.share_version/created_at` |
| 6 | `9f22dbe09a11` | `auth_sessions`, `refresh_tokens` (+IXs) |
| 7 | `b3c8d1f09e22` | `users.status_revision`, new status CHECK incl. `suspended`; `admin_audit.before_status/after_status/status_revision`. **Downgrade refuses** if any driver is suspended |
| 8 | `c4a76be0139d` | `driver_vehicles`; `rides.vehicle_*`; `admin_audit.details` |
| 9 | `d72f9e014ac3` | `rides.cancelled_at/cancelled_by/cancellation_reason` + FK |
| 10 | `e83a01cf742d` | `driver_presence.resume_available` (server default true) |
| 11 | `f94b12de853e` | `mock_payments` |
| 12 | `7ba01cddd40c` | `ride_payments` + **data back-fill**: every already-COMPLETED ride gets a CONFIRMED payment with method ONLINE (if mock SUCCESS) or UNRECORDED, so historic earnings stay counted |
| 13 | `c51e8a2f90d4` (**head**) | `ride_ratings` + IX ratee_id |

There are **no seed scripts**. No demo users or fare policies are inserted; defaults live in code (`DEFAULT_POLICY`, 85/15 split). Admins are created by CLI/bootstrap.

## 8. Backups

`deploy/backup.py <destination>` uses SQLite's online backup API from a read-only source connection, creates the destination exclusively (no overwrite, mode 0600) and runs `PRAGMA integrity_check`. Only works for file-backed SQLite.

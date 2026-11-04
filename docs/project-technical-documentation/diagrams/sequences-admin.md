# Admin sequence diagrams

[← Back to index](../README.md)

## Approve / suspend / reinstate a driver

```mermaid
sequenceDiagram
  autonumber
  actor A as Admin
  participant DM as DriverManagement.save
  participant EP as POST /admin/drivers/{id}/{approve|suspend|reinstate}
  participant AS as admin_service.change_driver_status
  participant SS as session_service.stop_requests
  participant DB as DB
  A->>DM: choose driver, type reason, confirm
  DM->>EP: {version: status_revision, reason}
  EP->>AS: change_driver_status(admin, driver_id, action, body)
  AS->>AS: driver exists & role driver (404), reason 1–300
  AS->>AS: version int ≥0 (approve may omit = legacy)
  AS->>DB: exact retry? (status==new, revision==version+1, matching audit row) → return
  AS->>AS: revision mismatch → 409, wrong current status → 409
  AS->>DB: UPDATE users SET status=new, status_revision=version+1 WHERE status=old AND status_revision=version
  AS->>SS: stop_requests(driver): available=false, resume=false, invitations CLOSED, notify
  AS->>DB: INSERT admin_audit (before/after status, revision)
  AS-->>DM: user.public()
```

## Save vehicle details

```mermaid
sequenceDiagram
  participant VE as VehicleEditor.save
  participant EP as PUT /admin/drivers/{id}/vehicle
  participant AS as admin_service.save_driver_vehicle
  participant DB as DB
  VE->>EP: {registration, model, color, reason, version}
  AS->>AS: validate, registration upper-cased, regex [A-Z0-9][A-Z0-9 -]{3,19}
  AS->>DB: no-op UPDATE users (row lock to serialize with acceptance)
  AS->>AS: disabled → 409, driver has active ride → 409, version mismatch → 409
  AS->>DB: upsert driver_vehicles, version+1
  AS->>DB: INSERT admin_audit action 'driver.vehicle.updated', details JSON {before, after}
```

## Fare policy save (optimistic concurrency)

```mermaid
sequenceDiagram
  participant FS as FareSettings.save
  participant EP as PUT /admin/fare-settings
  participant SV as fare_service.save
  participant DB as fare_policies
  FS->>EP: {version, reason, policy}
  SV->>DB: current() latest version
  SV->>SV: version must equal current (409)
  SV->>SV: validate(policy): decimals, booleans, timezone, ≤20 zones
  SV->>DB: INSERT version+1 (PK collision → 409)
  SV-->>FS: settings(): {version, policy, history[20]}
```

## Revenue share save

```mermaid
sequenceDiagram
  participant RV as RevenueSettings.save
  participant EP as PUT /admin/revenue-share
  participant SV as revenue_service.save
  participant DB as revenue_share_settings
  RV->>EP: {version, driver_pct, company_pct, effective_from|null, reason}
  SV->>SV: version == latest (409), percentages 0–100, 2 dp, sum = 100
  SV->>SV: effective_from null → now, else tz-aware, future, ≤366 days
  SV->>DB: INSERT version+1 with previous_*_pct from active split
```

## Audit history

```mermaid
sequenceDiagram
  participant AA as AdminAudit.jsx
  participant L as GET /admin/audit?page&category&q
  participant D as GET /admin/audit/{category}/{id}
  participant SV as admin_service
  AA->>L: list
  L->>SV: audit(): UNION ALL of admin_audit, fare_policies, revenue_share_settings, JOIN users for actor_name, ILIKE search, 20/page
  AA->>D: "View changes"
  D->>SV: audit_detail(): before/after field table
```

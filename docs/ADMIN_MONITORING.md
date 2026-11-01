# Admin monitoring and rider financial privacy

## Update

Stop both local servers, run `git pull --ff-only` from the repository root, then restart Flask and Vite as usual. This update has no dependency, environment-variable, Google-key or database-migration changes. Keep your working Maps, Places and Routes configuration.

## Rider receipts

Riders see pickup/destination, driver details, ride state, route estimates and their confirmed fare components (including any surge). They do **not** receive the driver/company settlement, percentage split, allocated driver amount, company amount or share-version metadata.

This filtering happens in the backend response serializer for trip details, workspace/history, booking, and repeated booking responses. The frontend independently refuses to render the settlement section for rider roles, even if presented with an old/incorrect payload. Assigned drivers still see their own financial details; admins retain operational financial visibility. Other drivers cannot access an unrelated completed ride.

## Admin overview

The overview uses current database records, not placeholder totals:

- Active rides: searching, assigned, arriving, waiting and in-progress.
- Searching and completed ride counts.
- Fresh available drivers: approved/active drivers, available without an active assignment, whose location capture and receipt timestamps are within 90 seconds.
- Stale available drivers: otherwise available drivers with missing/stale location; these cannot match.
- Pending driver applications.
- All-time allocated driver and company amounts from the settlement ledger, labeled as allocations rather than cash transfers or profit.

The existing realtime invalidation and periodic refresh update these counters. Counters can briefly change during concurrent activity; they are an operational view, not a point-in-time financial report. Riders and ordinary drivers do not receive admin metrics.

## Audit history

Open **Admin → Audit history**. Filter by driver reviews (approvals, suspensions and reinstatements), fare changes or revenue-share changes. Search by reason, admin name or action. Results are ordered by save time and paginated in groups of 20; no source rows are deleted or truncated for pagination.

Every entry shows actor, timestamp, reason, category and target. **View changes** shows:

- Driver review: driver identity and recorded before/after status. Legacy approval entries retain pending → active details.
- Fare policy: fields changed relative to the prior immutable version, including detailed zone centre, radius, multiplier, weekdays and window.
- Revenue share: previous active percentages at save time, new percentages, and the new effective date/time. A scheduled change is recorded when saved and may take effect later.

The history combines existing immutable driver audit records, fare-policy versions and revenue-setting versions. It does not create invented historical events, allow editing/deletion, or imply that login/ride events are included. Existing records are available immediately without a backfill.

## Verify

1. As rider, open a completed trip and history. The total fare remains visible; driver/company allocations do not appear.
2. As driver, check the earnings page. Existing allocated earnings remain unchanged.
3. As admin, check ride and driver counters on Overview.
4. Approve a driver or save a fare/revenue setting with a reason. Open Audit history and search for the reason, then inspect before/after values.
5. Attempt the audit APIs with a rider or driver token; access is denied. Trip details requested with the rider token contain no settlement object.

SQLite tests and fixture-backed browser checks verify these behaviors. SQL Server integration, production scaling, incident actions and payment transfers remain separate work.

Driver suspension and reinstatement are described in [driver management](DRIVER_MANAGEMENT.md). Apply the latest migrations when upgrading to that feature; the no-migration note above applies only to the earlier monitoring update.

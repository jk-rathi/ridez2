# Pre-trip cancellation

Riders can stop a search or cancel an assigned ride before it starts. Assigned drivers can cancel before starting the trip. Cancellation is permitted in `SEARCHING` (rider only), `ASSIGNED`, `ARRIVING` and `WAITING`. It is not permitted after a successful OTP start or after completion/timeout. Mid-trip interruption requires a separate incident workflow.

## What users see

Select **Cancel request** during search, or **Cancel ride** after assignment. Choose a reason and optionally add details. **Other** requires an explanation. Reasons are shared with the other participant and retained in ride history.

**Keep ride** closes the review without cancelling anything. For drivers, reviewing cancellation hides the trip-start/progress actions. Returning to a waiting trip clears any previously typed OTP, so the visible input and enabled Start button remain consistent. **Confirm cancellation** sends the request to the server; the interface waits for confirmation.

The rider and assigned driver receive the existing realtime update and reload authoritative state. A notice shows who cancelled, why and when. The assigned driver ends offline and may choose to go available again with a fresh location. Riders may request a new quote and book again. A new quote is necessary because retrying a previously booked quote returns that same cancelled ride.

The recent notice is shown for ten minutes when there is no active/newer trip, can be dismissed locally and is restored on reload during that interval. The complete record remains in history. Cancelling an unassigned search closes invitations but does not force its invited drivers offline.

## Records and races

The server writes one cancellation actor ID, timestamp and reason alongside the status transition. It closes pending invitations, releases both active-participant claims when assigned, updates the driver's offline state and writes notification events in the same transaction. A successful assignment remains recorded as an assigned search-round outcome; cancellation does not rewrite the earlier matching result.

Retries of an already-cancelled ride return the original actor/time/reason and never replace them with a retry's details. A concurrent acceptance, arrival or start can change the state before cancellation commits. The server uses a conditional state write and returns 409 when the client must refresh/review. If OTP start wins, cancellation is refused. If cancellation wins, a stale start cannot revive the ride. Search timeouts remain `NO_DRIVER_FOUND` rather than being relabelled as cancellation.

Only the rider and assigned driver can cancel. Unrelated users cannot access the ride, and admins cannot bypass the trip workflow through this endpoint. Suspended assigned drivers can still cancel a pre-start assignment. Cancelled rides retain vehicle/fare snapshots, but cannot yield new live map coordinates or earnings allocations.

Legacy searching-cancellation clients that omit a reason remain compatible and record a generic search-cancellation description. Newly assigned-ride cancellations require 1–300 characters. Existing historical cancellations retain unknown actor/time/reason where those were never recorded; the migration does not invent them.

## Money and commercial policy

Cancellation does not collect a payment, charge a fee, issue a refund, create a settlement or promise free cancellation. Payment collection is not connected. Commercial fee, no-show, compensation and refund rules remain business decisions for a future payment/policy milestone.

## Update and verify

Stop local servers, pull, and run from the repository root on Windows:

```powershell
git pull --ff-only
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

Restart the frontend normally. Linux/macOS uses `.venv/bin/flask --app run db upgrade` from `backend`. Render applies migrations on startup after **Manual Deploy → Deploy latest commit**. No new dependencies or Google-key changes are required.

Check searching cancellation; both rider/driver cancellation at assigned, arriving and waiting stages; Keep ride; shared reasons and persisted history; offline driver/new booking recovery; and cancellation rejection after OTP start. Automated concurrency checks use SQLite and do not establish SQL Server lock behavior.

# Driver suspension and reinstatement

Admins can manage drivers under **Admin → Drivers**, or the driver management section of Overview. Search by name, mobile or permanent account code, filter by status, and paginate through all matches in groups of 20.

Select **Approve driver**, **Suspend driver** or **Reinstate driver** to open a review form. Read the effect, enter a reason and use the explicit confirmation button. Cancel review makes no change. Suspension reasons are visible to the driver and should be written accordingly.

## Rules

| Action | Before | After | Effect |
| --- | --- | --- | --- |
| Approve | Pending | Active | Approved but offline; fresh location required to go available |
| Suspend | Active | Suspended | Stops availability, closes pending invitations and blocks accepting new rides |
| Reinstate | Suspended | Active | Remains offline; the driver chooses when to go available again |

Suspension preserves sign-in, refresh sessions, earnings and ride history. It also preserves an assigned ride in any pre-trip or in-progress state. The assigned driver may keep updating location, progress that ride, verify the ride's OTP and complete it with its existing fare/revenue rules. Once the trip ends, tracking stops and new work stays blocked until reinstatement.

An immediate mid-trip safety intervention requires the separate incident workflow; suspension is not a cancellation or emergency-stop action. Disabled accounts remain distinct and cannot be reactivated through driver reinstatement. Pending applications must be approved before suspension.

The driver sees a suspension banner, the latest review reason and time, and no availability/acceptance controls. The driver can still use trip controls on an assigned ride. Reinstatement removes the suspension banner and restores the offline availability control. Existing expired/closed invitations are not revived, and a driver is not invited repeatedly for the same searching ride.

## Audit and concurrency

Every successful change writes an immutable audit entry with the admin, reason, timestamp, before/after status and resulting status revision. **Admin → Audit history → Driver reviews** includes all three actions. Historical entries describe their recorded transition, regardless of the driver's current status. Old approval entries remain readable without inventing new historical events.

Status mutations use `status_revision`, returned in driver account/list responses. Send it as integer `version` with a reason. Stale decisions return 409 and require reloading/reviewing the current driver. Retrying the same completed action with the same original version, admin and reason returns the existing result without another audit entry. A retry from an older suspension/reinstatement cycle cannot change the current state. Legacy approval clients may omit version; new clients should supply it.

Suspension, availability and acceptance serialize through the driver's account row, with status checks on assignment. Matching rechecks current eligibility before writing invitations. Transactions keep the status change, offline state, invitation cleanup, notification and audit record together. SQLite checks do not establish SQL Server lock/concurrency behavior.

## Update

Stop both servers. From the repository root on Windows:

```powershell
git pull --ff-only
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

On Linux/macOS, use `.venv/bin/flask --app run db upgrade` and `.venv/bin/python run.py` from `backend`. Restart the frontend with `npm.cmd run dev` on Windows or `npm run dev` elsewhere. No new dependencies or Google key changes are required.

The migration adds a suspended driver status, status revisions and audit snapshot columns. It preserves accounts, sessions, rides and old approval history. Downgrading refuses while any driver remains suspended; review those accounts before attempting a downgrade.

## Verify

1. As an admin, search for an active driver and suspend them with a reason. Confirm their availability and pending invitations stop, and the suspended-driver total increases.
2. As that driver, reload or sign in again. The suspension banner/reason remains; new availability and acceptance are blocked.
3. Repeat with a driver already assigned a ride. That ride stays assigned. Complete the normal pickup → rider OTP → trip → completion flow and check earnings.
4. Reinstate the driver. They remain offline and must obtain a fresh location to go available. Their old invitations do not reappear.
5. Inspect all three review actions in Audit history, including before/after values. Try a stale version or a non-admin API request; neither can change the driver's status.

Normal completion now keeps active drivers available when they opted to remain online and have fresh GPS. Suspension and reinstatement still stop availability and clear that next-trip choice; finishing a suspended trip does not re-enable it. See [driver availability](DRIVER_AVAILABILITY.md).

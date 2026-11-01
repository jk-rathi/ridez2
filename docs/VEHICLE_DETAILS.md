# Vehicle records and prominent pickup details

After the driver accepts, the rider sees a large driver name, high-contrast car number, car colour/model, confirmed fare and the OTP required to start. Pickup and destination use larger type. The map follows these details on mobile and sits alongside them on wider screens. Fare components remain available under **View fare breakdown**. Once the trip starts, the pickup OTP is hidden from that trip card. The driver sees the rider's name, assigned vehicle, fare and large trip-action buttons; the rider OTP is never returned to the driver.

The app does not invent ratings, photos, pickup arrival times or missing car details. Existing rides without a vehicle snapshot show **Car number not provided**, with a reminder to confirm the car before boarding. This is distinct from the permanent DRV account code.

## Record a driver's actual car

1. Sign in as admin and open **Drivers**.
2. Select **Vehicle details** for a driver who has no active assignment.
3. Enter the car number, model, colour and a review reason. Example field placeholders are not stored unless explicitly entered. Confirm actual documents/car details before saving.
4. Save. Car numbers are normalized to uppercase; the admin list and driver's own account API include the current record. This is a human-reviewed record, not automatic verification against an external registry.

Car numbers accept 4–20 ASCII letters/digits/spaces/hyphens. Model and colour are limited to 80 and 40 characters; reasons to 300. The API is admin-only and uses the current vehicle version (zero when no record exists). Concurrent/stale edits return 409. Vehicle updates are recorded in **Audit history → Driver reviews**, including the reason and before/after values.

## Trip identity and privacy

Acceptance snapshots the assigned vehicle's registration, model and colour on the ride. Updates to the profile are blocked during an active assignment; future edits cannot change an existing receipt. Historical rides without a snapshot are not backfilled with a car that may never have served that ride.

Rider receipts retain their fare and vehicle/driver details without driver/company allocations. Driver and rider phone numbers have not been added to shared ride payloads. No phone masking, contact feature, payment collection or driver-rating system is implied by this screen update.

## Updating

Stop both local servers and run from the repository root on Windows:

```powershell
git pull --ff-only
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

Restart the frontend normally. Linux/macOS uses `.venv/bin/flask --app run db upgrade` from `backend`. Render runs the migration automatically when you select **Manual Deploy → Deploy latest commit**. Existing accounts, sessions, rides and review history are preserved. No additional packages or Google settings are needed.

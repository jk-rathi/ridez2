# Staying available after a trip

Active drivers now remain available automatically after completion when their GPS is fresh and bookings are enabled. The trip and earnings allocation finish as before, participant claims are released, and the driver can receive another request without tapping **Go available** again. Browser location updates continue while available.

While on an assigned trip, **Stay available after this trip** is checked by default. Uncheck it to finish the current trip and then go offline. This choice is persisted on the server and survives reload. Tracking continues for the current rider until the trip ends; it does not keep running after the driver finishes offline.

Checking it again requires a fresh GPS fix. Actual availability remains false while the driver is busy, so the setting cannot enable a second active assignment. After completion, **Go offline** remains available as usual.

Automatic availability is refused when:

- The driver is suspended or otherwise not active.
- The driver chose to go offline after the trip, or signed out.
- Location permission was denied/revoked and the browser reported it to the server.
- The latest location is stale (older than 90 seconds) or unavailable.
- New bookings are disabled, such as a disabled route simulator.

Permission revocation pauses future work even during an active trip. It does not cancel that trip. A recent GPS timestamp alone cannot override the persisted offline choice. If the browser cannot contact the server, it cannot confirm that choice; the existing location-freshness checks still exclude stale positions.

After completion with stale GPS, the driver remains offline and must explicitly go available with a fresh location. Drivers who remain online but later lose a fresh fix are excluded from matching until valid updates resume, under the existing freshness rules.

Retries of a completion request return the existing ride/settlement without re-enabling availability or creating a second allocation. Offline/logout/suspension and completion serialize through the driver's account row. Cancellation continues to leave an assigned driver offline; it is separate from successful completion.

## Update

There are no new dependencies or Google settings. Apply the new migration before restarting locally:

```powershell
git pull --ff-only
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

Restart the frontend normally. On Linux/macOS use `.venv/bin/flask --app run db upgrade` from `backend`. On Render, **Manual Deploy → Deploy latest commit** applies migrations automatically.

The migration adds a default stay-available preference to existing presence records; it does not itself mark an offline driver online or alter accounts, trips or earnings. Offline, logout and suspension actions then update that preference explicitly.

## Verify

1. Go available, accept and complete a trip. With fresh GPS, the dashboard should still show **Go offline** and accept another request.
2. On another trip, uncheck **Stay available after this trip**, reload and finish. The driver should be offline, with **Go available** shown.
3. Revoke location permission during a trip. The preference should turn off, the trip should remain assigned, and completion should not make the driver available.
4. Check suspension, logout from another device, stale GPS and completion retries. None should silently reactivate an opted-out or ineligible driver.

Backend concurrency checks use SQLite. SQL Server concurrency and production load remain separate validation gates.

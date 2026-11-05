# Admin analytics

**Admin → Analytics** shows rides, fares, demand and payments for a date range, and exports
the same range to Excel.

## Date range

Presets: last 7 / 30 / 90 days, this month, or a custom from–to range (at most 366 days).
Days are calendar days in the fare-settings timezone (Asia/Kolkata by default), inclusive at both
ends. Every tile, chart and the export use the same range.

- **Requested** rides count on the day they were booked.
- **Completed** rides, fares and revenue count on the day the trip ended.
- Arrows (▲/▼) compare with the previous period of the same length.

## What's on the page

| Section | Shows |
|---|---|
| Stat tiles | Rides completed / requested, gross fares, company revenue, average fare, cancellation rate, average driver rating (from riders), new riders and drivers |
| Rides per day | Requested vs completed, with a crosshair tooltip (arrow keys work too) |
| Gross fares per day | Fares of completed trips, including surge. The tooltip adds company revenue |
| Ride requests by hour | Demand by hour of day |
| Ride outcomes | Completed, cancelled, no driver found, still in progress |
| How completed trips were paid | Cash, online, not yet paid |

Every chart has a **Show table** toggle with the exact numbers.

## Excel export

**Download Excel** creates `ridez-report-<from>-to-<to>.xlsx` with four sheets: **Summary**
(the tiles), **Daily**, **Rides** (one row per ride requested in the range: status, rider and
driver name + code, places, distance, fare, surge, payment, completion/cancellation, revenue
split) and **Hourly demand**. Times are local to the fare-settings timezone. Mobile numbers are
not exported.

The file is sent as base64 inside the encrypted JSON channel (see
[API encryption](API_ENCRYPTION.md)), so it doesn't appear in the Network tab either.

API: `GET /api/v1/admin/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD` and
`GET /api/v1/admin/analytics/export?from=…&to=…` (admin only). Code: `backend/app/analytics_service.py`,
`frontend/src/Analytics.jsx`.

## Ride history download (riders, drivers and admins)

The **Your rides** (rider), **Trip history** (driver) and **Rides** (admin) pages have a
**Download ride history** bar with From/To dates (default: last 90 days). It downloads
`ridez-ride-history-<from>-to-<to>.xlsx`: one row per ride requested in the range, newest first,
with a totals line at the bottom.

| Who | Rides included | Money columns |
|---|---|---|
| Rider | their own rides | fare only, never the driver/company split |
| Driver | trips they were assigned | fare, their share % and their earnings |
| Admin | every ride | fare, driver amount and company amount |

API: `GET /api/v1/ride-history/export?from=YYYY-MM-DD&to=YYYY-MM-DD` (any signed-in user).

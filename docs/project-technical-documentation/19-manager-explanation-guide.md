# 19 — Manager explanation guide

[← Back to index](README.md) · Next: [20 — Technical interview questions →](20-technical-interview-questions.md)

Speaking scripts you can deliver nearly verbatim. Numbers and names are from the code.

## A. Project explanation (5–10 minutes)

> **1. What it is (30 s).** ridez.io is a taxi-booking web application with three workspaces in one React app: riders book trips, drivers accept and run them, and admins operate the platform. The backend is a single Flask service that serves the API, real-time updates over Socket.IO, and the compiled website from the same origin.
>
> **2. The rider journey (1.5 min).** A rider searches pickup and destination using Google Places autocomplete. The server calls Google's Routes API for real road distance and traffic-aware duration and calculates an itemized INR fare: base plus per-km plus per-minute, a minimum fare, and optional surge. That quote is stored, locked for five minutes, and records the fare-policy version, so later rate changes can't reprice it. When the rider confirms, the quote ID acts as an idempotency key, so double-clicks never create two rides.
>
> **3. Matching (1.5 min).** Matching starts at 500 metres from pickup and expands by 500 metres every 30 seconds up to a configurable 5 km. Only approved, available drivers whose GPS is fresher than 90 seconds are invited, and a driver is never invited twice for the same ride. The round deadlines live in the database, and a one-second background loop advances them, so a server restart catches up instead of losing searches. When drivers race to accept, a single conditional SQL update decides the winner, and a unique "active ride" claim per user guarantees nobody is double-booked.
>
> **4. The trip (1 min).** After acceptance the rider sees the driver's name, rating, and car number. The car details are snapshotted onto the ride. The driver moves the trip through head-to-pickup, arrived, start, and complete. Starting requires a six-digit OTP that is unique per ride and shown only to the rider. For Google-routed rides both sides see a live road map with ETA, refreshed every 10 seconds but cached server-side so we call Google at most once a minute per ride phase.
>
> **5. Money (1 min).** On completion we record a revenue allocation: by default 85% driver, 15% company, using whatever split was effective at that moment; admins can schedule future splits. A payment record opens as pending. The rider chooses cash, and the driver confirms receipt, or "online", which today is a clearly-labelled test QR flow with no real money. The first confirmation wins, and driver earnings count as received only after confirmation.
>
> **6. Admin and safety (1 min).** Admins approve, suspend, and reinstate drivers with mandatory reasons and version checks so two admins can't overwrite each other. Suspension stops new work but lets a driver finish their current trip. Admins edit versioned fare and surge rules and revenue splits, and every change appears in a searchable audit history with before and after values.
>
> **7. Security (45 s).** Login is mobile plus password. The access token is a 15-minute JWT kept only in memory; a rotating, single-use, HttpOnly refresh cookie restores the session for up to 30 days, and reusing an old refresh token revokes the session. Every request also checks the server-side session, so logout is immediate.
>
> **8. Status and limits (1 min).** It's deployed as one Docker container on Render with SQLite on a persistent disk, migrations at startup, and a readiness check. CI runs the test suite, builds the frontend and the image, and runs a container smoke test. The main limits are that it must run as a single process, payments are simulated, GPS depends on the driver keeping the browser tab open, and SQL Server is targeted but not validated.

## B. Architecture explanation (simple but accurate)

> "It's a modular monolith. The React app talks to a Flask REST API under `/api/v1` with a bearer token. Inside Flask, thin route handlers call service modules like `ride_service`, `matching`, and `fare_service`, which use SQLAlchemy to read and write the database. Everything important, including matching deadlines and outgoing notifications, is stored in the database. A background thread runs every second: it advances matching rounds and turns 'outbox' rows into Socket.IO messages. The browser treats those messages as 'something changed' and re-fetches one endpoint, `/workspace`, which returns everything that user's screen needs. If the socket drops, the browser polls every two seconds instead. Google is called from the server for routes and from the browser for maps and address search."

Draw: Browser → (REST + WebSocket) → Flask [routes → services → repositories] → DB; background loop → DB → Socket.IO → Browser; server → Google Routes; browser → Google Maps/Places.

## C. Feature speaking scripts

**Authentication.** "Mobile numbers are normalized to E.164 with Google's `phonenumbers` library, so formatting differences don't create duplicate accounts. Passwords are hashed with Werkzeug. Login failures always return the same message and do equal work for unknown users. We issue a 15-minute JWT plus a refresh cookie scoped to `/api/v1/auth`, HttpOnly and SameSite Lax. The refresh token is stored only as a SHA-256 hash and is single-use. The frontend serializes refreshes across tabs with the Web Locks API so tabs don't trip replay detection."

**Driver availability.** "A driver goes available by sending a fresh GPS fix with the request. The server checks accuracy (200 m or better), timestamp freshness, ordering, and physically plausible movement. The browser keeps sending location every 30 seconds while idle and every 10 seconds on a trip. The background loop marks any location older than 90 seconds as stale, which removes the driver from matching."

**Quotes and surge.** "Fares are Decimal-based and rounded half-up. Surge has three sources: scheduled circular zones around the pickup, traffic (Google's traffic duration divided by no-traffic duration), and demand (open requests divided by fresh drivers within 1 km). We take the single highest multiplier and cap it; we never multiply them together. The reason is stored on the quote and shown to the rider."

**Matching and acceptance.** "Booking creates the ride, the rider's active-ride claim, round 1, and invitations in one transaction, plus outbox events. Acceptance is one UPDATE whose WHERE clause re-checks everything: the ride is still searching, the round hasn't expired, this driver has a valid pending invitation, and they're still available with fresh GPS. If the row count is 1 they won; otherwise they get a 409."

**Trip and OTP.** "The OTP is an HMAC of the ride ID with a server secret, reduced to six digits. Nothing is stored, it survives restarts, and a code from one ride can never start another. Wrong attempts are rate-limited to five per minute per driver."

**Cancellation.** "Before the trip starts, the rider or assigned driver can cancel with a reason. It's recorded with who, when, and why, shown to both sides, and both active claims are released. The driver is left offline. In-progress trips can't be cancelled."

**Payments.** "Completion creates a pending payment for the quoted total. Cash is confirmed by the driver; online is currently a signed, 15-minute test QR link. Both go through one conditional update, so whichever confirmation commits first wins."

**Ratings.** "Each side rates the other once per completed trip with stars, tags, and an optional comment. Comments are visible only to admins. A retry with the same stars is idempotent; changing the rating is refused."

**Admin.** "Every admin write uses an optimistic version number. Driver status changes also call the same 'stop requests' routine as logout, so a suspended driver immediately stops receiving invitations. The audit page is a UNION over three history tables with escaped search and pagination."

**Real-time.** "We use a transactional outbox: events are rows written in the same transaction as the change, so you never notify about something that rolled back. The worker emits them within a second. Events carry no data, so duplicates or missed events are harmless; the client just refetches."

## D. Demo script (if asked to show it)

1. Three browsers: admin, driver, rider (simulator mode works without Google).
2. Admin → Drivers → approve the driver with a reason; add vehicle details.
3. Driver → Go available (allow location).
4. Rider → enter pickup at the driver's location (or use DevTools Sensors), get the estimate, confirm.
5. Driver accepts → rider sees car and OTP → driver: head to pickup → arrived → enter OTP → start → complete.
6. Rider payment modal → pay by cash → driver "Cash received" → both rate.
7. Admin → overview metrics, audit history.

## E. One-line answers to "what did you learn / what's next?"

- **Hardest part:** making every state change race-safe with conditional updates and unique claims, and making the system restart-safe by persisting deadlines and events.
- **Next steps:** real payment gateway and mobile verification; reduce `/workspace` query load and add indexes; move off SQLite and add Redis to scale beyond one process; add CSP and shared rate limiting; frontend tests in CI.

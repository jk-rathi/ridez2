# 11 — Third-party integrations and external services

[← Back to index](README.md) · Next: [12 — State management →](12-state-management.md)

Only integrations actually present in the code are listed. There is **no** payment gateway, SMS, email, push notification, analytics, error tracking, object storage or cloud database integration.

## Google Routes API (server-side)

| Item | Detail |
| --- | --- |
| Why | Real road distance and traffic-aware duration for fares; road polylines for maps |
| Configured in | `GOOGLE_MAPS_SERVER_KEY`, `ROUTE_PROVIDER=google` (default outside development); validated in `create_app` (required in production when provider is Google) |
| Code | `backend/app/route_provider.py::compute`, called by `ride_service.quote`, `trip_map_service.trip_map`, CLI `check-routing --probe` |
| Request | `POST https://routes.googleapis.com/directions/v2:computeRoutes` JSON `{origin, destination (latLng), travelMode: DRIVE, routingPreference: TRAFFIC_AWARE, computeAlternativeRoutes: false, polylineQuality: OVERVIEW}` |
| Auth | Header `X-Goog-Api-Key: <server key>`; field mask `routes.distanceMeters,routes.duration,routes.staticDuration,routes.polyline.encodedPolyline` (limits billing tier/response size) |
| Sent | Pickup and destination coordinates only (labels are not sent) |
| Received | Distance (m), duration and static duration (`"123s"` strings), encoded polyline |
| Timeouts | 3 s connect, 10 s read; redirects disabled |
| Caching | Quotes: none (each quote calls Google). Trip maps: in-memory 60 s per `(ride, phase, source, target, at_destination)`, errors 10 s, concurrent callers coalesced |

**Error handling** (`route_provider.compute`):

| Condition | API response |
| --- | --- |
| Key missing | 503 `Google routing is not configured. Set GOOGLE_MAPS_SERVER_KEY…` |
| No destination coordinates | 400 `Select destination coordinates on the map or enter them manually` |
| `requests.Timeout` | 504 `The route service timed out. Try again shortly` |
| Other `RequestException` | 502 `The route service is unavailable. No fare was generated` |
| HTTP 429 | 503 `Google routing quota was reached…` |
| HTTP 401/403 | 502 `Google routing access was denied… Google reason: <ALLOW-LISTED CODE>` |
| Other non-200 | 502 `Google could not calculate this route…` |
| Empty `routes` | 422 `No driving route was found between these locations` |
| Malformed fields | 502 `The route provider returned an invalid estimate. Please retry` |

**If Google is unavailable:** no new quotes can be created in Google mode (explicitly no fallback to simulated data — product rule in `docs/PRODUCT_BLUEPRINT.md`); existing rides continue (matching, OTP, completion, payments don't need Google); trip maps show an error with "Refresh route" while trip controls keep working.

**Simulator alternative:** `ROUTE_PROVIDER=simulator` + `SIMULATOR_ENABLED=1` produces deterministic sample routes (labelled "simulated route" in UI). Quotes record their `provider`; booking refuses a quote whose provider differs from the current mode.

## Google Maps JavaScript API (browser)

| Item | Detail |
| --- | --- |
| Why | Interactive maps for picking points, showing quotes and live trips |
| Configured in | `frontend/.env.local` → `VITE_GOOGLE_MAPS_BROWSER_KEY` (and optional `VITE_GOOGLE_MAP_ID`, default `DEMO_MAP_ID`); Docker build args; `render.yaml` (`sync: false`) |
| Code | `frontend/src/googleMaps.js::loadMaps` (script loader), `GoogleRouteMap.jsx` (Map, `AdvancedMarkerElement`, `Polyline`, `geometry.encoding.decodePath`, `LatLngBounds`) |
| Auth | Browser key in the script URL — **public by design**; must be restricted by HTTP referrer and API in Google Cloud (documented in `docs/GOOGLE_MAPS_SETUP.md`) |
| Error handling | Missing key → explanatory error; script `onerror`; 15 s load timeout; `window.gm_authFailure` → `ridez.maps.error` event → "access was denied" message + Retry button |
| If unavailable | Booking still possible via manual coordinate fields; trip map hidden behind an error; no impact on backend |

## Google Places API (New) (browser)

| Item | Detail |
| --- | --- |
| Why | Address autocomplete |
| Code | `frontend/src/AddressSearch.jsx`: `maps.importLibrary('places')`, `AutocompleteSessionToken`, `AutocompleteSuggestion.fetchAutocompleteSuggestions({input, sessionToken, locationBias:{center: pickup, radius: 50000}})`, `placePrediction.toPlace().fetchFields({fields:['formattedAddress','location']})` |
| Sent | Typed text (≥ 3 chars, debounced 300 ms), optional bias centre |
| Received | Up to 5 predictions; selected place address and lat/lng |
| Attribution | "Powered by Google" image under suggestions |
| Errors | "Address search unavailable. Check Places API (New) and browser-key restrictions, or select on the map." / "Unable to load this address…" |

## Google Maps deep link (no API key)

`TripStatsCard.googleNavigationUrl` builds `https://www.google.com/maps/dir/?api=1&destination=<lat,lng>&travelmode=driving&dir_action=navigate`, opened in a new tab for drivers. No data is sent from the backend.

## Browser platform APIs

| API | Where | Purpose |
| --- | --- | --- |
| Geolocation | `useDriverLocation.js::getPosition` | Driver location and rider "Use my location" |
| Permissions API | `useDriverLocation` | Detect revoked location permission |
| Web Locks (`navigator.locks`) | `authSession.js` | Cross-tab refresh serialization |
| BroadcastChannel | `authSession.js` | Cross-tab sign-out |
| sessionStorage | `RideWorkspace.jsx` | Remember dismissed payment prompts |
| `crypto.randomUUID` | `FareSettings.jsx` | New zone IDs |

## jsDelivr CDN

`GET /api/v1/docs` returns HTML that loads `swagger-ui-dist@5` CSS/JS from `cdn.jsdelivr.net`. If unavailable, only the Swagger UI page breaks; `/openapi.json` still works.

## Render (hosting)

`render.yaml` defines one Docker web service (Starter plan, 1 instance, manual deploys, health check `/api/v1/ready`, 1 GB disk at `/var/data`), generates `JWT_SECRET` and `USER_CODE_SECRET`, and expects the Google keys to be entered in the dashboard. Render terminates TLS and forwards `X-Forwarded-For/Proto` (trusted through `TRUST_PROXY_HEADERS=1`). Details: [15](15-deployment-and-execution.md).

## GitHub Actions

`.github/workflows/checks.yml` runs on push to `main` and on pull requests: Python 3.12 + Node 22, `pip install -r backend/requirements.lock`, `pytest -q`, `npm ci && npm run build`, `docker build`, `python deploy/smoke.py --image ridez:ci`.

## Dependency on external services — impact matrix

| Service down | Effect |
| --- | --- |
| Google Routes | No new Google quotes; trip map errors; rides in progress unaffected |
| Google Maps JS / Places | No map/autocomplete; manual coordinates still work |
| jsDelivr | Swagger UI only |
| Render | Whole app down (single instance) |
| Browser geolocation denied | Driver cannot go available; active trip preserved; rider can still type/select pickup |

# 01 — Technology stack

[← Back to index](README.md) · Next: [02 — Folder and file structure →](02-folder-and-file-structure.md)

Versions below are taken from `frontend/package.json` (ranges) and `backend/requirements.lock` (exact pins). Rationale is labelled **documented** when stated in the repo (code comments, README, `docs/`) and **inferred** otherwise.

## Frontend

| Technology | Version | Role in this app | Why it is used |
| --- | --- | --- | --- |
| React | `^19.0.0` | All UI components (`frontend/src/*.jsx`) | Documented: blueprint mandates "React with JavaScript". Function components + hooks only; no class components. |
| react-dom | `^19.0.0` | `createRoot` in `main.jsx` | Required renderer for React 19 |
| React Router | `^7.0.0` (`react-router-dom`) | `BrowserRouter`, nested `Routes`, `Navigate`, `NavLink`, `useParams` in `main.jsx` and `TestPayment.jsx` | Client-side routing for `/rider/*`, `/driver/*`, `/admin/*`, `/test-payment/:token` |
| Vite | `^6.0.0` | Dev server with proxy (`vite.config.js`), production build to `frontend/dist` | Inferred: fast dev server; built-in `import.meta.env` for `VITE_*` browser variables; simple proxy for `/api` and `/socket.io` WebSockets |
| @vitejs/plugin-react | `^4.3.0` | JSX transform and fast refresh | Standard Vite React integration |
| socket.io-client | `^4.8.1` | `io()` in `RideWorkspace.jsx::useWorkspace` | Must match the Flask-SocketIO (python-socketio 5 / Engine.IO 4) protocol |
| lucide-react | `^0.468.0` | Icons across all pages | Inferred: lightweight, tree-shakeable SVG icons |
| qrcode | `^1.5.4` | `QRCode.toDataURL` in `TestPayment.jsx` | Generates the mock payment QR image in the browser |
| Plain CSS | — | `frontend/src/styles.css` | No CSS framework |

No state-management library (Redux, Zustand, React Query) is used. State is held in React hooks plus a small module-level store in `authSession.js`. See [12 — State management](12-state-management.md).

No TypeScript, no ESLint config, no frontend unit-test runner. There is one Playwright browser script (`frontend/tests/qr-session.browser.cjs`) that is not wired into CI.

## Backend

| Technology | Version | Role | Why |
| --- | --- | --- | --- |
| Python | 3.12 (`.python-version` = `3.12.12`) | Runtime | Documented in README: 3.14 is unsupported by the pinned `pyodbc` wheel |
| Flask | 3.1.0 | HTTP framework, app factory `create_app()` in `app/__init__.py`, one Blueprint `api` | Documented in blueprint: "Flask REST API" |
| Werkzeug | 3.1.9 | Password hashing (`generate_password_hash` / `check_password_hash`), `ProxyFix`, routing | Comes with Flask |
| Flask-SQLAlchemy | 3.1.1 | `db = SQLAlchemy()` session and model base | ORM integration |
| SQLAlchemy | 2.1.6 | 2.0-style `select()`, `update()`, `delete()` statements in repositories/services | Needed for conditional `UPDATE … WHERE` used for concurrency control |
| Flask-Migrate / Alembic | 4.1.0 / 1.20.1 | `flask db upgrade`; 13 migrations in `backend/migrations/versions` | Versioned schema changes; `/ready` checks DB is at the migration head |
| Flask-SocketIO / python-socketio / python-engineio | 5.5.1 / 5.17.0 / 4.15.1 | `socketio` server in `app/realtime.py`, `async_mode='threading'` | Push `workspace.changed` notifications; threading mode avoids eventlet/gevent |
| simple-websocket / wsproto | 1.1.0 / 1.3.2 | WebSocket transport for threading mode | Transitive dependency of Flask-SocketIO |
| PyJWT | 2.10.1 | HS256 access tokens in `session_service.py` | Stateless bearer token, but paired with a DB session check |
| itsdangerous | 2.2.0 | `URLSafeTimedSerializer` for mock QR tokens (`test_payment_routes.py`) | Signed, time-limited capability URLs; ships with Flask |
| phonenumbers | 8.13.55 | `services.normalize()` → E.164 | Ensures one account per real number regardless of formatting |
| requests | 2.32.5 | Google Routes call in `route_provider.compute` | Simple HTTP client with timeouts |
| python-dotenv | 1.2.1 | Loads `backend/.env` in `create_app` (never overrides real env vars) | Local configuration |
| tzdata | 2025.2 | IANA zone data for `zoneinfo` in `fare_service` (surge schedules) | Needed on systems (Windows, slim containers) without OS tz database |
| pyodbc | 5.2.0 | SQL Server driver | Documented target DB is SQL Server. **Not used** in the default SQLite deployment |
| gunicorn | 26.2.0 | Production WSGI server (`gunicorn.conf.py`) | One `gthread` worker with 100 threads |
| pytest | 8.3.4 | Backend tests in `backend/tests` | Note: it is also installed in the production image because it is in `requirements.lock` |

## Database

| Environment | Database | Source |
| --- | --- | --- |
| Local development | SQLite file (`DATABASE_URL` default `sqlite:///ridez.db`) | `app/__init__.py` |
| Tests | In-memory SQLite (`sqlite://`) or temp files for concurrency tests | `backend/tests/test_auth.py::app` fixture |
| Render (Blueprint) | SQLite on persistent disk `sqlite:////var/data/ridez.db` | `render.yaml` |
| Intended production | SQL Server via `mssql+pyodbc` | README, `.env.example`. **No validation exists**, and the Docker image does not include Microsoft ODBC Driver 18 |

## External services

| Service | Used from | Purpose |
| --- | --- | --- |
| Google Routes API (`routes.googleapis.com/directions/v2:computeRoutes`) | Backend `route_provider.py` | Road distance/duration/polyline for quotes and live trip maps |
| Google Maps JavaScript API (`maps.googleapis.com/maps/api/js`, script libraries `marker`, `geometry`; `places` is loaded on demand with `importLibrary`) | Browser `googleMaps.js` | Map rendering, polyline decoding, Places autocomplete |
| Google Places API (New) | Browser `AddressSearch.jsx` | `AutocompleteSuggestion.fetchAutocompleteSuggestions`, `place.fetchFields` |
| jsDelivr CDN | `/api/v1/docs` HTML | Loads Swagger UI assets |
| Render | Hosting | Docker web service, TLS, persistent disk |
| GitHub Actions | CI | `.github/workflows/checks.yml` |

Details: [11 — Third-party integrations](11-third-party-integrations.md).

## Tooling and infrastructure

| Tool | File | Purpose |
| --- | --- | --- |
| Docker (multi-stage) | `Dockerfile` | Stage 1 `node:22-bookworm-slim` builds the SPA; stage 2 `python:3.12-slim-bookworm` runs Gunicorn as user `ridez` (uid 10001) |
| Render Blueprint | `render.yaml` | One Docker web service, Starter plan, 1 GB disk at `/var/data` |
| Native Render scripts | `deploy/render-build.sh`, `deploy/render-start.sh` | Alternative to Docker: Python runtime build/start |
| GitHub Actions | `.github/workflows/checks.yml` | pytest → npm build → docker build → `deploy/smoke.py` |
| Smoke test | `deploy/smoke.py` | Starts the real image, checks migrations, login, cookies, booking, cancel, restart persistence, logout |
| Backup | `deploy/backup.py` | Online SQLite backup with integrity check |

## How the pieces fit (why this stack)

- **Single origin.** Flask serves the SPA (`web.py`), REST API and Socket.IO from one origin. This is why there is no CORS configuration and why the refresh cookie can be `SameSite=Lax` with `Path=/api/v1/auth`. In development Vite's proxy recreates the same-origin setup.
- **Threading instead of async.** `Flask-SocketIO(async_mode='threading')` + Gunicorn `gthread` keeps everything in ordinary blocking Python, compatible with SQLAlchemy sessions and the `requests` library, with no monkey-patching. The README states this was deliberately chosen to avoid installing Redis for local Windows development.
- **SQLAlchemy Core-style statements** (`update(...).where(...)`) are central: almost every race-sensitive operation is a conditional UPDATE whose `rowcount` decides who won.

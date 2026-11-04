# 16 — Dependencies and package explanation

[← Back to index](README.md) · Next: [17 — Technical decisions →](17-technical-decisions.md)

## 1. Frontend (`frontend/package.json`)

Versions are semver ranges; the exact resolved versions are in `package-lock.json`.

| Package | Range | Kind | Purpose | Used in | Essential? |
| --- | --- | --- | --- | --- | --- |
| `react` | ^19.0.0 | runtime | Component model, hooks, context | every `.jsx` | Yes |
| `react-dom` | ^19.0.0 | runtime | `createRoot` rendering | `main.jsx` | Yes |
| `react-router-dom` | ^7.0.0 | runtime | `BrowserRouter`, `Routes`, `Route`, `Navigate`, `Link`, `NavLink`, `useNavigate`, `useParams` | `main.jsx`, `TestPayment.jsx` | Yes |
| `socket.io-client` | ^4.8.1 | runtime | Real-time invalidation events | `RideWorkspace.jsx` | Yes (polling fallback exists) |
| `lucide-react` | ^0.468.0 | runtime | SVG icons | most components | No (cosmetic) |
| `qrcode` | ^1.5.4 | runtime | QR data URLs for mock payments | `TestPayment.jsx` | Only for test payments |
| `vite` | ^6.0.0 | dev | Dev server, proxy, production bundler | `vite.config.js`, scripts | Yes (build) |
| `@vitejs/plugin-react` | ^4.3.0 | dev | JSX/Fast Refresh | `vite.config.js` | Yes (build) |

Google Maps JS is **not** an npm dependency; it is loaded at runtime from `maps.googleapis.com` by `googleMaps.js`.

### npm scripts

| Script | Command | Use |
| --- | --- | --- |
| `dev` | `vite --host 0.0.0.0` | Local dev server on :5173 (reachable from LAN devices) |
| `build` | `vite build` | Production bundle in `frontend/dist` (used by Docker, CI, `render-build.sh`) |
| `preview` | `vite preview --host 0.0.0.0` | Serve the built bundle locally |

## 2. Backend direct dependencies (`backend/requirements.txt`)

| Package | Pinned | Purpose | Where used | Essential? |
| --- | --- | --- | --- | --- |
| Flask | 3.1.0 | Web framework | everywhere | Yes |
| Flask-SQLAlchemy | 3.1.1 | ORM integration, `db` | `__init__.py`, all data access | Yes |
| Flask-Migrate | 4.1.0 | Alembic integration, `flask db` CLI | `__init__.py`, `migrations/env.py` | Yes |
| PyJWT | 2.10.1 | Access tokens | `session_service.py`; tests | Yes |
| phonenumbers | 8.13.55 | Mobile normalization | `services.normalize` | Yes |
| pytest | 8.3.4 | Tests | `backend/tests` | Dev only (but installed in prod image) |
| pyodbc | 5.2.0 | SQL Server DBAPI | only when `DATABASE_URL` is `mssql+pyodbc` | No for SQLite deployments |
| Flask-SocketIO | 5.5.1 | WebSocket server | `realtime.py`, `run.py` | Yes |
| requests | 2.32.5 | Google Routes HTTP | `route_provider.py` | Yes in Google mode |
| python-dotenv | 1.2.1 | `.env` loading, `check-routing` | `__init__.py` | Convenience |
| tzdata | 2025.2 | IANA tz database for `zoneinfo` | `fare_service` | Yes for surge schedules on slim/Windows |
| gunicorn | 26.2.0 | Production server | `gunicorn.conf.py`, Docker CMD | Yes in production |

## 3. Transitive dependencies (`backend/requirements.lock`)

| Package | Version | Pulled in by | Role |
| --- | --- | --- | --- |
| SQLAlchemy | 2.1.6 | Flask-SQLAlchemy | ORM/Core; conditional UPDATE statements |
| alembic | 1.20.1 | Flask-Migrate | Migrations; `/ready` reads the script head |
| Mako | 1.4.3 | alembic | Revision templates |
| Werkzeug | 3.1.9 | Flask | Routing, password hashing, `ProxyFix` |
| Jinja2 / MarkupSafe | 3.1.6 / 3.0.4 | Flask | Templating (unused by app code) |
| itsdangerous | 2.2.0 | Flask | Mock QR token signing (used directly) |
| click | 8.5.0 | Flask | CLI commands |
| blinker | 1.9.0 | Flask | Signals |
| python-socketio / python-engineio | 5.17.0 / 4.15.1 | Flask-SocketIO | Socket.IO protocol |
| bidict | 0.24.1 | python-socketio | Session maps |
| simple-websocket / wsproto / h11 | 1.1.0 / 1.3.2 / 0.16.0 | python-engineio | WebSocket transport in threading mode |
| certifi, charset-normalizer, idna, urllib3 | 2026.10.23, 3.5.2, 3.20, 2.8.0 | requests | HTTPS/TLS |
| typing_extensions | 4.16.0 | SQLAlchemy/alembic | Typing backports |
| packaging, pluggy, iniconfig | 26.3, 1.7.0, 2.3.1 | pytest/gunicorn | |

The lock file is what Docker, CI, the README and root `requirements.txt` install, so builds are reproducible.

## 4. Unused or questionable dependencies

| Item | Observation |
| --- | --- |
| `pytest` in the runtime lock | Installed into the production image; harmless but unnecessary |
| `pyodbc` + `libodbc2` | Present for a SQL Server target that the deployment doesn't use; the ODBC Driver 18 itself is not installed, so SQL Server cannot work from the image as-is |
| `Jinja2` | Not used by app code (only via Flask internals) |
| `repositories.by_id` | Unused function (code, not a package) |

No unused **npm** packages were found: every listed package is imported by `frontend/src`.

## 5. What depends on what (critical paths)

| If this package broke… | …this would fail |
| --- | --- |
| SQLAlchemy / Flask-SQLAlchemy | Everything |
| PyJWT | All authenticated endpoints and sockets |
| Flask-SocketIO | App boot (imported in `create_app`), worker loop, real-time updates |
| requests | Google quotes and trip maps |
| phonenumbers | Register, login, bootstrap |
| tzdata | Surge zone schedules (`ZoneInfo('Asia/Kolkata')`) on systems without tz data |
| socket.io-client | Live updates (polling still works at 2 s) |
| qrcode | QR image only |

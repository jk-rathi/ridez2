# Architecture diagrams

[← Back to index](../README.md)

## 1. High-level system

```mermaid
flowchart LR
  subgraph Browser["Browser (React 19 SPA, built by Vite)"]
    UI["Pages & components<br/>main.jsx, RideWorkspace.jsx, ..."]
    AS["authSession.js<br/>in-memory access token"]
    API["api.js<br/>fetch wrapper"]
    SIO["socket.io-client"]
    GEO["navigator.geolocation<br/>useDriverLocation.js"]
    GMJS["Google Maps JS + Places<br/>(browser key)"]
  end

  subgraph Server["Single Python process (Flask + Flask-SocketIO)"]
    WEB["web.py<br/>serves built SPA"]
    BP["Blueprint 'api' /api/v1<br/>routes.py, ride_routes.py,<br/>test_payment_routes.py"]
    SVC["Service modules<br/>ride_service, fare_service, matching,<br/>session_service, payment_service, ..."]
    REPO["Repositories<br/>ride_repository.py, repositories.py"]
    RT["realtime.py<br/>Socket.IO server + 1 s worker loop"]
  end

  DB[("SQL database via SQLAlchemy<br/>SQLite (dev & Render)<br/>SQL Server (targeted, not validated)")]
  GR["Google Routes API<br/>computeRoutes (server key)"]

  UI --> API --> BP
  UI --> AS
  AS -- "POST /auth/refresh (cookie)" --> BP
  SIO <-- "workspace.changed" --> RT
  GEO --> API
  UI --> GMJS
  BP --> SVC --> REPO --> DB
  SVC -- "HTTPS, X-Goog-Api-Key" --> GR
  RT -- "advance() + dispatch()" --> DB
  WEB -. "index.html / assets" .-> Browser
```

## 2. Backend module dependency graph

Arrows mean "imports / calls".

```mermaid
flowchart TD
  init["app/__init__.py<br/>create_app()"] --> routes["routes.py<br/>api blueprint, authenticated()"]
  init --> ride_routes["ride_routes.py"]
  init --> tpr["test_payment_routes.py"]
  init --> realtime["realtime.py"]
  init --> web["web.py"]

  routes --> services["services.py<br/>ApiError, register, login, trip_otp"]
  routes --> session["session_service.py"]
  routes --> ride_service["ride_service.py"]
  ride_routes --> ride_service
  ride_routes --> location["location_service.py"]
  ride_routes --> payment["payment_service.py"]
  ride_routes --> rating["rating_service.py"]
  ride_routes --> fare["fare_service.py"]
  ride_routes --> revenue["revenue_service.py"]
  ride_routes --> admin["admin_service.py"]
  ride_routes --> tripmap["trip_map_service.py"]
  tpr --> payment

  ride_service --> matching["matching.py"]
  ride_service --> route_provider["route_provider.py"]
  ride_service --> fare
  ride_service --> revenue
  ride_service --> payment
  ride_service --> rating
  ride_service --> location
  ride_service --> repo["ride_repository.py"]
  tripmap --> route_provider
  tripmap --> ride_service
  fare --> repo
  matching --> repo
  admin --> session
  admin --> repo
  services --> users_repo["repositories.py"]
  session --> repo
  realtime --> session
  realtime --> matching

  repo --> models["models.py (19 tables)"]
  users_repo --> models
```

## 3. Deployment topology (Render Blueprint, `render.yaml`)

```mermaid
flowchart LR
  user((User browser / phone)) -- HTTPS --> proxy["Render TLS proxy<br/>(X-Forwarded-For/Proto)"]
  proxy --> container
  subgraph container["Docker container (Dockerfile, runtime stage)"]
    start["/app/start.sh<br/>chown /var/data → gosu ridez<br/>flask db upgrade<br/>optional bootstrap-admin"]
    gunicorn["gunicorn -c gunicorn.conf.py wsgi:app<br/>1 worker · gthread · 100 threads"]
    worker["post_worker_init → start_worker()<br/>1 s matching/outbox loop"]
    dist["/app/frontend_dist<br/>(Vite build from stage 1)"]
    start --> gunicorn --> worker
    gunicorn --> dist
  end
  container --> disk[("Persistent disk /var/data<br/>sqlite:////var/data/ridez.db")]
  container -- HTTPS --> google["routes.googleapis.com"]
  user -- "Maps JS / Places (browser key)" --> gmaps["maps.googleapis.com"]
```

## 4. Local development topology

```mermaid
flowchart LR
  browser["Browser http://localhost:5173"] --> vite["Vite dev server<br/>npm run dev"]
  vite -- "proxy /api and /socket.io (ws)" --> flask["python run.py<br/>socketio.run on :5000<br/>+ start_worker()"]
  flask --> sqlite[("backend/instance/ridez.db<br/>(default sqlite:///ridez.db)")]
  flask -. "instance/jwt.key, instance/codes.key<br/>auto-generated secrets" .- sqlite
```

Note: Flask-SQLAlchemy resolves the relative SQLite URL `sqlite:///ridez.db` inside the Flask instance folder (`backend/instance/`). **(inferred from Flask-SQLAlchemy 3.x behaviour; the `instance/` folder in this checkout contains the generated key files.)**

# Deploy ridez.io on Render

This repository includes a Render Blueprint (`render.yaml`) for **one Docker web service**. It serves the compiled React website, Flask APIs and Socket.IO from the same HTTPS origin. Gunicorn runs one threaded worker and starts the persisted matching loop. Render supplies TLS and process supervision.

The initial deployment uses SQLite on a persistent disk at `/var/data/ridez.db`. This is suitable for a single-instance pilot. The disk requires a paid Render instance; the Blueprint selects Starter and a 1 GB disk. Review Render's current price before creating it. Do not use an ephemeral/free instance for this database. Do not scale horizontally or add Gunicorn workers: the current in-process matching, socket delivery and rate limiters require one process. Production traffic capacity and SQL Server concurrency are separate validation gates.

## Existing Render service using the Python runtime

Keep your existing service. This repository also supports Render's native Python runtime. In **Settings → Build & Deploy**, set:

| Setting | Value |
| --- | --- |
| Root Directory | Empty (repository root) |
| Build Command | `sh deploy/render-build.sh` |
| Start Command | `sh deploy/render-start.sh` |
| Health Check Path | `/api/v1/ready` |

Use **Environment** to set `PYTHON_VERSION=3.12.12` and `NODE_VERSION=22`. The repository also pins those versions; an existing Render environment override takes precedence. The previous default Python 3.14 is not the tested runtime for the locked backend dependencies.

Keep all existing database, Google Maps, bootstrap and session settings. Do not regenerate `JWT_SECRET` or `USER_CODE_SECRET`, or replace `DATABASE_URL`. `APP_ENV=production` and `TRUST_PROXY_HEADERS=1` are needed on Render. Browser Google Maps keys must be present during the build as `VITE_GOOGLE_MAPS_BROWSER_KEY`. Restarting a native service now applies migrations and optional admin bootstrap, then starts the same one-worker Gunicorn configuration as Docker. The frontend and APIs share one service/origin.

Select **Manual Deploy → Deploy latest commit** after updating the commands. A root `requirements.txt` is included for compatibility, but `pip install -r requirements.txt` by itself does not build the frontend. Use the full build script above. If the old start command is `python app.py`, `gunicorn app:app`, or a development server, replace it with the start script above.

The Docker Blueprint remains supported. Changing to native Python does not change storage durability: retain any existing persistent disk or database, and keep the database URL pointing to it. Free ephemeral SQLite still loses data across restarts/redeploys.

## First deployment

1. Open Render and select **New → Blueprint**, connect GitHub, and select `jk-rathi/ridez.io` on `main`. Render reads the root `render.yaml`. Review the plan and disk before creating resources. Alternatively create a Docker Web Service manually using the settings below.
2. Supply these two values securely in Render's environment settings:
   - `GOOGLE_MAPS_SERVER_KEY`: server-only Google key with **Routes API** enabled.
   - `VITE_GOOGLE_MAPS_BROWSER_KEY`: browser-public key with **Maps JavaScript API** and **Places API (New)** enabled.
   The Docker build reads `VITE_...` values as build arguments. Render makes service environment variables available as Docker build arguments when the Dockerfile declares them. Only the browser key belongs in a `VITE_` variable; never put server/database credentials there. Browser key changes require rebuilding the service.
3. Keep the generated `JWT_SECRET` and `USER_CODE_SECRET` values. Render generates them independently. Keep both stable across deploys; changing the code secret changes the OTP for rides that have not started yet. Do not put secrets in Git or share them in chat.
4. Deploy. The image builds the frontend and installs locked Python dependencies. At runtime, after Render attaches the disk, `start.sh` initializes its directory ownership, drops to the application user, applies migrations and starts Gunicorn on Render's `PORT` (default 10000). Do not move SQLite migrations into a build/pre-deploy command: the persistent disk is needed at runtime. Failed migrations stop startup.
5. Once healthy, open the assigned `https://…onrender.com` address. Add **that exact origin** to the browser key's allowed website referrers, including `https://your-service.onrender.com/*`. Keep local referrers if still needed. For a custom domain, add its exact HTTPS referrer too. Configure the server key's IP restrictions for Render's published outbound IP addresses/ranges, rather than your local computer's IP. Keep Google billing and quotas configured.
6. In the Render service's **Shell**, create the first admin interactively:
   ```sh
   gosu ridez python -m flask --app wsgi create-admin
   ```
   The image initializes disk ownership as root, then runs the web process as `ridez`. Use `gosu ridez` for commands in Render Shell too. No accounts or default passwords are seeded. Local development accounts are not automatically uploaded.

The Blueprint sets:

| Setting | Value |
| --- | --- |
| Runtime | Docker; root `Dockerfile`; repository root build context |
| Instance count | 1 |
| Health check | `/api/v1/ready` |
| Persistent disk | `/var/data`, 1 GB |
| Database | `sqlite:////var/data/ridez.db` |
| `APP_ENV` | `production` |
| `TRUST_PROXY_HEADERS` | `1` (Render's trusted TLS proxy only) |
| `ROUTE_PROVIDER` | `google` |
| `SIMULATOR_ENABLED` | `0` |
| Automatic deploys | Disabled; deploy reviewed updates manually |

For a manual Web Service, create the disk and set every environment variable shown in `render.yaml`, including distinct random secrets of at least 32 characters. Leave Build/Start commands at the Dockerfile defaults. Render terminates HTTPS; do not configure a separate frontend Static Site or CORS. The app preserves the incoming Host and trusts one proxy for forwarded protocol/client IP. Enable `TRUST_PROXY_HEADERS` only behind the trusted proxy.

## Create admin without paid Shell access

On an existing Render Web Service, open **Environment** and add:

| Key | Value |
| --- | --- |
| `BOOTSTRAP_ADMIN` | `1` |
| `BOOTSTRAP_ADMIN_MOBILE` | Your admin mobile, including country code |
| `BOOTSTRAP_ADMIN_NAME` | Your display name (optional; defaults to Admin) |
| `BOOTSTRAP_ADMIN_PASSWORD` | Your chosen strong password, 10–128 characters |

Save and deploy the latest commit. Startup runs migrations and creates this admin before serving traffic. The deploy logs report **Bootstrap admin created successfully.** Sign in on the normal website using that mobile/password. No public admin-registration or bootstrap URL is exposed, and bootstrap credentials are removed from the web worker's environment after startup.

Use a mobile number that is not already registered as a rider/driver. Bootstrap refuses to promote existing users, reactivate disabled admins or reset passwords. On later restarts, an existing active admin is left unchanged; use the original password. Invalid or incomplete bootstrap settings stop startup with an error that names the missing setting without printing its value.

**Persistent database:** after confirming sign-in, set `BOOTSTRAP_ADMIN=0` and remove the three bootstrap credential/name variables. Keep the regular database/JWT/code secrets. The admin stays in the database.

**Free Render with ephemeral SQLite:** this method avoids paying for Shell, but it does not make the database persistent. A restart/redeploy can lose all local accounts, rides and earnings. Leaving bootstrap enabled recreates just the admin when the database is empty; it does not restore other data. Disabling bootstrap and redeploying on ephemeral storage can therefore remove your only admin. Use persistent storage before relying on the app for real records. The supplied Blueprint still uses a paid persistent disk; this change does not provision a free durable database.

## Check the deployment

- `/` and a direct reload of `/rider/history` load the website. `/api/v1/health` responds; `/api/v1/ready` must return HTTP 200 with `database: true` and `matching_worker: true`. Readiness returns 503 when the schema is outdated, the database is inaccessible or the loop stalls. It does not make billable Google calls and does not establish Google key readiness.
- Register a rider and driver in separate browser sessions. Sign in as admin and approve the driver. Check fresh GPS availability, Google address search, quote, acceptance, pickup, ride OTP, completion, earnings and rider receipt privacy.
- Refresh the page and confirm sign-in is restored. Check logout, all-device logout, suspension and reinstatement. The Socket.IO connection should reach WebSocket transport, with API polling retained as fallback.
- Restart the service and confirm accounts, an unstarted ride's OTP, trips and sessions persist. Test Google routing with your real keys; local container checks use explicit simulator mode and do not validate live billing, quotas or routes.

If you only want a labelled demonstration without Google, explicitly change `ROUTE_PROVIDER=simulator` and `SIMULATOR_ENABLED=1` in Render. This enables sample route/fare data, not live Google routing. The default Blueprint keeps Google mode and disables the simulator.

## Updates, backups and recovery

1. Create a backup before deploying a schema change. In Render Shell:
   ```sh
   gosu ridez python backup.py /var/data/backups/ridez-before-update.db
   ```
   Choose a new filename for every backup. The command uses SQLite's consistent backup API and checks integrity; it refuses to overwrite files. Keep sufficient disk space, remove old retained backups deliberately and download copies off the same disk using Render's supported SSH/file-transfer access. A backup stored only on the same disk is not disaster recovery.
2. Review Render's managed disk snapshot/restore options and rehearse recovery on a separate staging service. Never replace a live SQLite database while Gunicorn is writing it. Restore the database and its matching secrets together; retain `JWT_SECRET` and `USER_CODE_SECRET` securely outside the service as part of recovery planning.
3. Select **Manual Deploy → Deploy latest commit** after tests pass. The disk persists; migrations rerun safely before the server accepts traffic. A disk-backed, single-instance deploy can interrupt active connections. Clients resync using persisted rides/deadlines after restart. Schedule a quiet period for schema changes.
4. Rolling back an image does not automatically roll back its database. Use a schema-compatible commit or a rehearsed database restore; do not blindly downgrade migrations. The suspension migration intentionally refuses downgrade while drivers are suspended.

To import an existing local installation, first make a consistent backup of its database and securely preserve its signing/code secrets. Transfer the backup to the disk through supported Render access while the app is stopped, set the corresponding secrets securely and run migrations. Simply uploading code creates a new installation; it does not transfer local accounts or Google configuration.

## Runtime limits

This deployment packages the current app for Render; it does not add payment processing, recovery/incident policies, multi-instance operation or a production load guarantee. The in-process rate limits remain bounded to one process and reset on restart. Add shared rate limiting and a broker/worker ownership model before scaling. Protect database exports, maintain backups, configure Google quotas and monitor readiness/errors.

The default image includes the unixODBC runtime for the pinned pyodbc dependency, but **does not install Microsoft ODBC Driver 18**. Do not change `DATABASE_URL` to SQL Server without adding that driver to a reviewed image and completing SQL Server migration/concurrency tests. No SQL Server validation or managed database provisioning is implied by this Blueprint.

## Local verification of the deployment image

```sh
docker build -t ridez:local .
python deploy/smoke.py --image ridez:local
```

The smoke test creates its own temporary database volume and random test secrets, checks the actual production image, restarts it, verifies login/OTP persistence and logout revocation, then removes only its own test container and volume. In the managed cloud environment, builds use its required proxy/CA settings; normal Render builds use their platform trust store. CI runs the backend tests, frontend build, Docker build and image smoke test without Google credentials.

## Startup error: missing DATABASE_URL / JWT_SECRET / USER_CODE_SECRET

A manually created Docker Web Service does not automatically import `render.yaml`. Blueprint environment variables apply when the service is created/synchronized through a Blueprint; adding that file to Git alone does not configure an existing manual service.

Open the existing Render **Web Service → Environment** and add any missing settings:

| Key | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `DATABASE_URL` | `sqlite:////var/data/ridez.db` for this guide's persistent SQLite setup |
| `JWT_SECRET` | A securely generated random secret of at least 32 characters |
| `USER_CODE_SECRET` | A different securely generated random secret of at least 32 characters |

For a new installation, generate two values on your own computer with:

```sh
python -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))"
```

Paste them into the two secret environment fields in Render, not into Git or chat. If these secrets already exist for an installation you are retaining, restore their existing values instead of generating replacements. Keep `APP_ENV=production`.

Confirm the service has a persistent disk mounted at `/var/data`, then save the environment changes and deploy/redeploy. These are runtime service settings, not frontend variables; do not add a `VITE_` prefix. The latest startup error lists only the missing variable names, never their values. The Google keys and other settings in the guide are still required for live routing.

For mock QR payment testing, enable `TEST_PAYMENTS_ENABLED=1` in Render Environment and deploy. See [TEST_PAYMENTS.md](../TEST_PAYMENTS.md). These simulations do not transfer money.

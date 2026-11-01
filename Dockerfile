# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --strict-ssl=true
COPY frontend/ ./
# Only browser-public settings belong in frontend build arguments.
ARG VITE_GOOGLE_MAPS_BROWSER_KEY
ARG VITE_GOOGLE_MAP_ID
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production PORT=10000
RUN apt-get update && apt-get install -y --no-install-recommends libodbc2 ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 ridez && useradd --uid 10001 --gid ridez --create-home ridez
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.lock
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/wsgi.py backend/gunicorn.conf.py ./
COPY deploy/start.sh deploy/backup.py ./
COPY --from=frontend /build/dist ./frontend_dist
RUN chmod -R a+rX /app && mkdir -p /var/data /app/instance && chown -R ridez:ridez /var/data /app/instance \
    && chmod 755 /app/start.sh
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','10000')+'/api/v1/ready',timeout=4)"
ENTRYPOINT ["/app/start.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]

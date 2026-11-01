#!/bin/sh
# Native Render runs as its own service user; no Docker-specific gosu is needed.
set -eu
cd "$(dirname "$0")/../backend"
if [ ! -f frontend_dist/index.html ]; then
    echo 'Frontend build is missing. Set Render Build Command to: sh deploy/render-build.sh' >&2
    exit 1
fi
python -m flask --app wsgi db upgrade
if [ "${BOOTSTRAP_ADMIN:-0}" = 1 ]; then
    python -m flask --app wsgi bootstrap-admin
fi
unset BOOTSTRAP_ADMIN BOOTSTRAP_ADMIN_MOBILE BOOTSTRAP_ADMIN_NAME BOOTSTRAP_ADMIN_PASSWORD
exec gunicorn --config gunicorn.conf.py wsgi:app

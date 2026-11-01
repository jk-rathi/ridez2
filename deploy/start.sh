#!/bin/sh
set -eu
# Render attaches its disk after image creation. Initialize mount ownership once,
# then run migrations and Gunicorn as the unprivileged application user.
if [ "$(id -u)" = 0 ]; then
    mkdir -p /var/data
    chown ridez:ridez /var/data
    exec gosu ridez "$0" "$@"
fi
# Render persistent disks are attached at runtime, not during build/pre-deploy.
# The single instance runs migrations before accepting HTTP traffic.
if [ "${1:-}" = gunicorn ]; then
    python -m flask --app wsgi db upgrade
    if [ "${BOOTSTRAP_ADMIN:-0}" = 1 ]; then
        python -m flask --app wsgi bootstrap-admin
    fi
    # The web worker does not need bootstrap credentials in its environment.
    unset BOOTSTRAP_ADMIN BOOTSTRAP_ADMIN_MOBILE BOOTSTRAP_ADMIN_NAME BOOTSTRAP_ADMIN_PASSWORD
fi
exec "$@"

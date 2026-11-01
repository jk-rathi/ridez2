from collections import defaultdict, deque
from functools import wraps
from time import monotonic
from flask import Blueprint, current_app, g, jsonify, request
from .services import ApiError, login, register

api = Blueprint('api', __name__)


@api.after_request
def no_store(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@api.errorhandler(ApiError)
def api_error(error):
    response = jsonify(error=error.message)
    response.status_code = error.status
    response.headers['Cache-Control'] = 'no-store'
    if error.status == 401 and request.path.endswith(('/auth/refresh', '/auth/logout-all')):
        from .session_service import cookie
        cookie(response)
    return response


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError('A JSON object is required')
    return data


def authenticated(role=None):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get('Authorization', '')
            from .session_service import authenticate
            if not header.startswith('Bearer '):
                raise ApiError('Please sign in again', 401)
            g.user, g.auth_claims = authenticate(header[7:])
            if role and g.user.role != role:
                raise ApiError('You do not have access to this workspace', 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


@api.before_request
def limit_auth():
    if request.method == 'POST' and request.path.endswith(('/auth/login', '/auth/register')):
        # Development limiter only; deploy a shared Redis limiter before multiple workers.
        buckets = current_app.extensions.setdefault('auth_attempts', defaultdict(deque))
        now = monotonic()
        for key in list(buckets):
            while buckets[key] and buckets[key][0] <= now - 60:
                buckets[key].popleft()
            if not buckets[key]:
                del buckets[key]
        key = request.remote_addr
        attempts = buckets[key]
        if len(attempts) >= 10:
            raise ApiError('Too many attempts. Try again in one minute', 429)
        attempts.append(now)


@api.get('/health')
def health():
    running = monotonic() - current_app.extensions.get('matching_last_tick', float('-inf')) < 10
    return jsonify(status='ok', stage='location-matching', routing_diagnostics_version=1, route_provider=current_app.config['ROUTE_PROVIDER'], matching_worker=running, simulator=current_app.config['SIMULATOR_ENABLED'], storage='sqlite-development' if current_app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite') else 'sql-server')


@api.post('/auth/register')
def registration():
    return jsonify(user=register(body()).public()), 201


@api.post('/auth/login')
def sign_in():
    from .session_service import check_origin, cookie
    check_origin(require_header=False)
    data, token = login(body())
    return cookie(jsonify(data), token)


@api.get('/me')
@authenticated()
def me():
    return jsonify(user=g.user.public())


@api.get('/driver/overview')
@authenticated('driver')
def driver():
    from .ride_service import snapshot
    data = snapshot(g.user)
    return jsonify(approval=g.user.status, trips=sum(ride['status'] == 'COMPLETED' for ride in data['rides']), allocated_earnings=data['allocated_earnings'], availability_enabled=g.user.status == 'active' and data['booking_enabled'], available=data['available'])


@api.get('/admin/overview')
@authenticated('admin')
def admin():
    from .ride_service import snapshot
    return jsonify(snapshot(g.user))


@api.get('/openapi.json')
def specification():
    from .spec import SPEC
    return jsonify(SPEC)


@api.get('/docs')
def docs():
    return '''<!doctype html><html lang="en"><head><title>ridez API</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head><body><div id="swagger"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:'/api/v1/openapi.json',dom_id:'#swagger'})</script></body></html>'''


@api.post('/auth/refresh')
def refresh_session():
    from .session_service import check_origin, refresh, cookie
    check_origin()
    data, token = refresh()
    return cookie(jsonify(data), token)


@api.post('/auth/logout')
def logout_session():
    from .session_service import check_origin, logout, cookie
    check_origin()
    logout()
    return cookie(jsonify(status='signed_out'))


@api.post('/auth/logout-all')
@authenticated()
def logout_all_sessions():
    from .session_service import check_origin, logout, cookie
    check_origin()
    logout(g.user, all_devices=True)
    return cookie(jsonify(status='signed_out_all_devices'))


@api.get('/ready')
def readiness():
    from sqlalchemy import text
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path
    from . import db
    try:
        expected = current_app.extensions.get('migration_head')
        if not expected:
            config = Config()
            config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'migrations'))
            expected = ScriptDirectory.from_config(config).get_current_head()
            current_app.extensions['migration_head'] = expected
        versions = set(db.session.execute(text('SELECT version_num FROM alembic_version')).scalars())
        database_ready = versions == {expected}
        worker_ready = monotonic() - current_app.extensions.get('matching_last_tick', float('-inf')) < 10
        ready = database_ready and worker_ready
    except Exception:
        db.session.rollback()
        database_ready = worker_ready = ready = False
    return jsonify(status='ready' if ready else 'not_ready', database=database_ready, matching_worker=worker_ready), 200 if ready else 503

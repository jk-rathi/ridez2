import time
from datetime import timedelta
from flask import current_app, request
from flask_socketio import SocketIO, join_room
from sqlalchemy import select, delete
from . import db
from .models import User, OutboxEvent
from .services import ApiError
from .location_service import utcnow

socketio = SocketIO(async_mode='threading', logger=False, engineio_logger=False)


def init_realtime(app):
    socketio.init_app(app)
    app.extensions['ride_connections'] = {}

    @socketio.on('connect')
    def connect(auth):
        try:
            if not isinstance(auth, dict) or not isinstance(auth.get('token'), str):
                return False
            from .session_service import authenticate
            user, payload = authenticate(auth['token'])
        except ApiError:
            return False
        current_app.extensions['ride_connections'][request.sid] = (user.id, payload['exp'], payload['sid'])
        join_room(f'user:{user.id}')
        if user.role == 'admin':
            join_room('admins')

    @socketio.on('disconnect')
    def disconnect(reason=None):
        current_app.extensions['ride_connections'].pop(request.sid, None)


def disconnect_invalid():
    # Recheck access before sending: expired/disabled sessions must not stay subscribed.
    from .session_service import valid_session
    for sid, (user_id, expires, session_id) in list(current_app.extensions['ride_connections'].items()):
        user = db.session.get(User, user_id)
        if expires <= time.time() or not user or user.status == 'disabled' or not valid_session(session_id, user_id):
            socketio.server.disconnect(sid)
            current_app.extensions['ride_connections'].pop(sid, None)


def dispatch():
    disconnect_invalid()
    events = db.session.scalars(select(OutboxEvent).where(OutboxEvent.delivered_at.is_(None)).order_by(OutboxEvent.created_at).limit(200)).all()
    for event in events:
        # Event IDs support deduplication. Fetch canonical state after any reconnect.
        socketio.emit('workspace.changed', {'event_id': event.id, 'server_time': utcnow().isoformat()+'Z'}, to=f'user:{event.user_id}' if event.user_id is not None else 'admins')
        event.delivered_at = utcnow()
    db.session.execute(delete(OutboxEvent).where(OutboxEvent.delivered_at < utcnow()-timedelta(days=7)))
    db.session.commit()


def tick(app):
    from .matching import advance
    with app.app_context():
        try:
            advance()
            dispatch()
            app.extensions['matching_last_tick'] = time.monotonic()
        except Exception:
            db.session.rollback()
            raise


def start_worker(app):
    if app.extensions.get('matching_worker'):
        return

    def loop():
        while True:
            try:
                tick(app)
            except Exception:
                # Avoid database exception payloads, which may contain sensitive coordinates.
                app.logger.error('Matching worker tick failed; retrying. Check database readiness and migrations.')
            socketio.sleep(1)

    app.extensions['matching_worker'] = socketio.start_background_task(loop)

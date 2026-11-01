"""Revocable access sessions and single-use, hashed refresh credentials."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
from flask import current_app, request
from sqlalchemy import update
from . import db
from .models import User, AuthSession, RefreshToken, DriverPresence, Invitation
from .services import ApiError

COOKIE = 'ridez_refresh'
COOKIE_PATH = '/api/v1/auth'


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(require_header=True):
    # Custom header prevents cross-site form submissions; no CORS is enabled.
    if require_header and request.headers.get('X-Session-Request') != '1':
        raise ApiError('Session request header is required', 403)
    origin = request.headers.get('Origin')
    allowed = {request.host_url.rstrip('/'), *current_app.config['AUTH_TRUSTED_ORIGINS']}
    if origin and origin not in allowed:
        raise ApiError('Request origin is not allowed', 403)
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        raise ApiError('Cross-site session requests are not allowed', 403)


def cookie(response, token=None):
    response.headers['Cache-Control'] = 'no-store'
    if token:
        response.set_cookie(COOKIE, token, max_age=current_app.config['REFRESH_SESSION_DAYS']*86400,
                            httponly=True, secure=current_app.config['AUTH_COOKIE_SECURE'],
                            samesite='Lax', path=COOKIE_PATH)
    else:
        response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True,
                               secure=current_app.config['AUTH_COOKIE_SECURE'], samesite='Lax')
    return response


def payload(user, session):
    issued = datetime.now(timezone.utc)
    expires = min(issued + timedelta(minutes=15), session.expires_at.replace(tzinfo=timezone.utc))
    token = jwt.encode({'sub': str(user.id), 'sid': session.id, 'iat': issued, 'exp': expires},
                       current_app.config['JWT_SECRET'], algorithm='HS256')
    return {'access_token': token, 'expires_in': max(0,int((expires-issued).total_seconds())),
            'expires_at': int(expires.timestamp()), 'user': user.public()}


def new_refresh(session):
    value = secrets.token_urlsafe(48)
    db.session.add(RefreshToken(token_hash=digest(value), session_id=session.id, created_at=now()))
    return value


def issue(user):
    session = AuthSession(id=str(uuid4()), user_id=user.id, created_at=now(),
                          expires_at=now()+timedelta(days=current_app.config['REFRESH_SESSION_DAYS']))
    db.session.add(session)
    token = new_refresh(session)
    db.session.commit()
    return payload(user, session), token


def valid_session(session_id, user_id=None):
    session = db.session.get(AuthSession, session_id) if isinstance(session_id, str) else None
    if not session or session.revoked_at or session.expires_at <= now():
        return None
    if user_id is not None and session.user_id != user_id:
        return None
    return session


def authenticate(token):
    try:
        claims = jwt.decode(token, current_app.config['JWT_SECRET'], algorithms=['HS256'],
                            options={'require': ['sub','sid','iat','exp']})
        user = db.session.get(User, int(claims['sub']))
        if not user or user.status == 'disabled' or not valid_session(claims['sid'], user.id):
            raise ValueError()
        return user, claims
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise ApiError('Please sign in again', 401)


def stop_requests(user_id):
    user = db.session.get(User, user_id)
    if user and user.role == 'driver':
        from .ride_repository import lock_driver
        lock_driver(user_id)
        db.session.execute(update(DriverPresence).where(DriverPresence.driver_id==user_id).values(available=False, resume_available=False))
        db.session.execute(update(Invitation).where(Invitation.driver_id==user_id, Invitation.status=='PENDING').values(status='CLOSED'))
        from .ride_repository import notify
        notify(user_id)


def revoke(session):
    session.revoked_at = now()
    stop_requests(session.user_id)


def refresh():
    value = request.cookies.get(COOKIE, '')
    record = db.session.get(RefreshToken, digest(value)) if value and len(value) <= 128 else None
    session = valid_session(record.session_id) if record else None
    user = db.session.get(User, session.user_id) if session else None
    if not session or not user or user.status == 'disabled':
        if session:
            revoke(session)
            db.session.commit()
        raise ApiError('Please sign in again', 401)
    # A conditional write makes a refresh credential single-use across workers.
    changed = db.session.execute(update(RefreshToken).where(RefreshToken.token_hash==record.token_hash,
                                 RefreshToken.used_at.is_(None)).values(used_at=now())).rowcount
    if changed != 1:
        revoke(session)
        db.session.commit()
        raise ApiError('Session credential was already used. Please sign in again', 401)
    token = new_refresh(session)
    db.session.commit()
    return payload(user, session), token


def logout(user=None, all_devices=False):
    if all_devices:
        db.session.execute(update(AuthSession).where(AuthSession.user_id==user.id,
                           AuthSession.revoked_at.is_(None)).values(revoked_at=now()))
        stop_requests(user.id)
    else:
        value = request.cookies.get(COOKIE, '')
        record = db.session.get(RefreshToken, digest(value)) if value and len(value)<=128 else None
        session = db.session.get(AuthSession, record.session_id) if record else None
        if not session:
            header = request.headers.get('Authorization', '')
            if header.startswith('Bearer '):
                try:
                    _, claims = authenticate(header[7:])
                    session = valid_session(claims['sid'])
                except ApiError:
                    pass
        if session:
            revoke(session)
    db.session.commit()
    # Disconnect revoked sockets now; dispatch also rechecks other server processes.
    from .realtime import disconnect_invalid
    disconnect_invalid()

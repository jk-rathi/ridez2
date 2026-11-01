from datetime import timedelta
import hashlib
import jwt
import pytest
from sqlalchemy import select, func
from app import db
from app.models import AuthSession, RefreshToken, User, DriverPresence, ActiveRide, Ride, Invitation
from app.realtime import socketio
from app.session_service import COOKIE, COOKIE_PATH, now
from test_auth import app, client, signup, signin, headers
from test_rides import actors, prepare, book, post

CSRF = {'X-Session-Request':'1'}


def refresh(client):
    return client.post('/api/v1/auth/refresh', headers=CSRF)


def test_refresh_cookie_rotation_hashes_and_profile(client, app):
    signup(client)
    login = signin(client)
    original = client.get_cookie(COOKIE, path=COOKIE_PATH)
    assert original.http_only and original.same_site == 'Lax' and original.path == COOKIE_PATH
    assert 'no-store' in login.headers['Cache-Control']
    assert COOKIE not in login.json and 'refresh_token' not in login.json
    with app.app_context():
        record = db.session.get(RefreshToken, hashlib.sha256(original.value.encode()).hexdigest())
        assert record and record.used_at is None
        assert record.token_hash != original.value
    result = refresh(client)
    assert result.status_code == 200
    assert client.get_cookie(COOKIE, path=COOKIE_PATH).value != original.value
    assert result.json['user'] == login.json['user']
    assert client.get('/api/v1/me',headers=headers(result)).status_code == 200
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(AuthSession)) == 1
        assert db.session.scalar(select(func.count()).select_from(RefreshToken)) == 2
        assert db.session.get(RefreshToken,hashlib.sha256(original.value.encode()).hexdigest()).used_at


def test_replayed_refresh_revokes_family_and_access(client, app):
    signup(client)
    login = signin(client)
    old = client.get_cookie(COOKIE,path=COOKIE_PATH).value
    renewed = refresh(client)
    new = client.get_cookie(COOKIE,path=COOKIE_PATH).value
    client.set_cookie(COOKIE,old,path=COOKIE_PATH)
    assert refresh(client).status_code == 401
    for token in (login,renewed):
        assert client.get('/api/v1/me',headers=headers(token)).status_code == 401
    client.set_cookie(COOKIE,new,path=COOKIE_PATH)
    assert refresh(client).status_code == 401
    assert client.get_cookie(COOKIE,path=COOKIE_PATH) is None


def test_logout_revokes_only_current_device_and_disconnects(client, app):
    signup(client)
    login = signin(client)
    other = app.test_client()
    second = signin(other)
    socket = socketio.test_client(app,auth={'token':login.json['access_token']})
    second_socket = socketio.test_client(app,auth={'token':second.json['access_token']})
    assert socket.is_connected() and second_socket.is_connected()
    assert client.post('/api/v1/auth/logout',headers=CSRF).status_code == 200
    assert not socket.is_connected() and second_socket.is_connected()
    assert client.get_cookie(COOKIE,path=COOKIE_PATH) is None
    assert client.get('/api/v1/me',headers=headers(login)).status_code == 401
    assert other.get('/api/v1/me',headers=headers(second)).status_code == 200
    assert refresh(client).status_code == 401
    assert refresh(other).status_code == 200
    assert client.post('/api/v1/auth/logout',headers=CSRF).status_code == 200
    second_socket.disconnect()


def test_logout_all_revokes_devices_and_refresh(client, app):
    signup(client)
    first = signin(client)
    other = app.test_client()
    second = signin(other)
    response = client.post('/api/v1/auth/logout-all',headers=CSRF|headers(first))
    assert response.status_code == 200
    for device,login in ((client,first),(other,second)):
        assert device.get('/api/v1/me',headers=headers(login)).status_code == 401
        assert refresh(device).status_code == 401
    assert signin(client).status_code == 200


@pytest.mark.parametrize('route',['refresh','logout','logout-all'])
def test_cookie_mutation_csrf_and_origin(client,route):
    signup(client)
    login = signin(client)
    path = '/api/v1/auth/'+route
    assert client.post(path,headers=headers(login)).status_code == 403
    assert client.post(path,headers=headers(login)|CSRF|{'Origin':'https://evil.example'}).status_code == 403
    assert client.post(path,headers=headers(login)|CSRF|{'Sec-Fetch-Site':'cross-site'}).status_code == 403
    assert client.get('/api/v1/me',headers=headers(login)).status_code == 200
    assert client.post(path,headers=headers(login)|CSRF|{'Origin':'http://localhost'}).status_code == 200


def test_login_rejects_cross_site_origin(client):
    signup(client)
    assert client.post('/api/v1/auth/login',json={'mobile':'+919876543210','password':'correct-horse-battery'},headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.get_cookie(COOKIE,path=COOKIE_PATH) is None


@pytest.mark.parametrize('change',['expired','disabled','revoked'])
def test_invalid_session_refresh_and_access_rejected(client,app,change):
    signup(client)
    login = signin(client)
    claims = jwt.decode(login.json['access_token'],app.config['JWT_SECRET'],algorithms=['HS256'])
    with app.app_context():
        session = db.session.get(AuthSession,claims['sid'])
        if change == 'expired':session.expires_at = now()-timedelta(seconds=1)
        elif change == 'revoked':session.revoked_at = now()
        else:db.session.get(User,session.user_id).status = 'disabled'
        db.session.commit()
    assert refresh(client).status_code == 401
    assert client.get('/api/v1/me',headers=headers(login)).status_code == 401
    assert not socketio.test_client(app,auth={'token':login.json['access_token']}).is_connected()


def test_expired_access_can_refresh_and_legacy_tokens_are_rejected(client,app):
    signup(client)
    login = signin(client)
    claims = jwt.decode(login.json['access_token'],app.config['JWT_SECRET'],algorithms=['HS256'])
    claims['iat'] = int((now()-timedelta(hours=1)).timestamp())
    claims['exp'] = claims['iat']+60
    expired = jwt.encode(claims,app.config['JWT_SECRET'],algorithm='HS256')
    assert client.get('/api/v1/me',headers={'Authorization':'Bearer '+expired}).status_code == 401
    result = refresh(client)
    assert result.status_code == 200
    del claims['sid']
    claims['exp'] = int((now()+timedelta(minutes=1)).timestamp())
    legacy = jwt.encode(claims,app.config['JWT_SECRET'],algorithm='HS256')
    assert client.get('/api/v1/me',headers={'Authorization':'Bearer '+legacy}).status_code == 401


def test_driver_logout_stops_matching_and_preserves_active_ride(client,app,actors):
    prepare(client,actors)
    ride = book(client,actors)
    driver = app.test_client()
    signin(driver,mobile=actors['driver']['mobile'],password='long-enough-password')
    assert driver.post('/api/v1/auth/logout',headers=CSRF).status_code == 200
    with app.app_context():
        assert not db.session.get(DriverPresence,actors['driver']['id']).available
        assert db.session.get(Invitation,(ride['id'],actors['driver']['id'])).status != 'PENDING'
    prepare(client,actors)
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel").status_code == 200
    ride = book(client,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code == 200
    signin(driver,mobile=actors['driver']['mobile'],password='long-enough-password')
    assert driver.post('/api/v1/auth/logout',headers=CSRF).status_code == 200
    with app.app_context():
        assert db.session.get(ActiveRide,actors['driver']['id']).ride_id == ride['id']
        assert db.session.get(Ride,ride['id']).status == 'ASSIGNED'
    login = signin(driver,mobile=actors['driver']['mobile'],password='long-enough-password')
    assert driver.get('/api/v1/workspace',headers=headers(login)).json['active_ride']['id'] == ride['id']


def test_cookie_secure_in_production_mode_setting(client,app):
    app.config['AUTH_COOKIE_SECURE'] = True
    signup(client)
    response = signin(client)
    assert 'Secure;' in response.headers['Set-Cookie']
    assert 'HttpOnly' in response.headers['Set-Cookie']


def test_bearer_session_must_belong_to_user(client,app):
    signup(client)
    login = signin(client)
    claims = jwt.decode(login.json['access_token'],app.config['JWT_SECRET'],algorithms=['HS256'])
    signup(client,mobile='+14155552671')
    claims['sub'] = '2'
    token = jwt.encode(claims,app.config['JWT_SECRET'],algorithm='HS256')
    assert client.get('/api/v1/me',headers={'Authorization':'Bearer '+token}).status_code == 401


def test_concurrent_refresh_has_one_winner_and_revokes_replay(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app import create_app
    config={'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
            'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "sessions.db"}',
            'JWT_SECRET':'session-race-test-only-secret-123456',
            'USER_CODE_SECRET':'session-race-code-test-secret-123456'}
    race_app=create_app(config)
    with race_app.app_context():db.create_all()
    with race_app.test_client() as device:
        signup(device)
        login=signin(device)
        credential=device.get_cookie(COOKIE,path=COOKIE_PATH).value
    barrier=Barrier(2)
    def attempt():
        with race_app.test_client() as device:
            device.set_cookie(COOKIE,credential,path=COOKIE_PATH)
            barrier.wait(timeout=5)
            return refresh(device).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=[pool.submit(attempt) for _ in range(2)]
        assert sorted(result.result() for result in results)==[200,401]
    restarted=create_app(config)
    with restarted.test_client() as device:
        assert device.get('/api/v1/me',headers=headers(login)).status_code==401
        device.set_cookie(COOKIE,credential,path=COOKIE_PATH)
        assert refresh(device).status_code==401


def test_session_survives_new_application_instance(tmp_path):
    from app import create_app
    config={'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
            'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "persist.db"}',
            'JWT_SECRET':'session-persist-test-secret-123456',
            'USER_CODE_SECRET':'session-persist-code-secret-123456'}
    original=create_app(config)
    with original.app_context():db.create_all()
    with original.test_client() as device:
        signup(device)
        login=signin(device)
        credential=device.get_cookie(COOKIE,path=COOKIE_PATH).value
    restarted=create_app(config)
    with restarted.test_client() as device:
        assert device.get('/api/v1/me',headers=headers(login)).status_code==200
        device.set_cookie(COOKIE,credential,path=COOKIE_PATH)
        renewed=refresh(device)
        assert renewed.status_code==200
        assert renewed.json['user']==login.json['user']


def test_logout_bearer_fallback_when_refresh_cookie_is_missing(client):
    signup(client)
    login=signin(client)
    client.delete_cookie(COOKIE,path=COOKIE_PATH)
    assert client.post('/api/v1/auth/logout',headers=CSRF|headers(login)).status_code==200
    assert client.get('/api/v1/me',headers=headers(login)).status_code==401

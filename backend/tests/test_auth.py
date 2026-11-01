from datetime import datetime, timedelta, timezone
import jwt
import pytest
from app import create_app, db
from app.models import User
from app.services import register


@pytest.fixture()
def app():
    app = create_app({'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'JWT_SECRET': 'test-jwt-secret-for-tests-only-123456', 'USER_CODE_SECRET': 'test-code-secret-for-tests-only-123456'})
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def signup(client, **overrides):
    return client.post('/api/v1/auth/register', json={'name': 'Asha', 'mobile': '+919876543210', 'password': 'correct-horse-battery', 'role': 'rider', **overrides})


def signin(client, **overrides):
    return client.post('/api/v1/auth/login', json={'mobile': '+919876543210', 'password': 'correct-horse-battery', **overrides})


def headers(response):
    return {'Authorization': f"Bearer {response.json['access_token']}"}


def test_register_login_profile_and_stable_code(client, app):
    created = signup(client)
    assert created.status_code == 201
    code = created.json['user']['user_code']
    assert code.startswith('RID-') and '9876543210' not in code
    assert 'password_hash' not in created.json['user']
    first, second = signin(client), signin(client)
    assert first.status_code == 200
    profile = client.get('/api/v1/me', headers=headers(first))
    assert profile.json['user']['user_code'] == second.json['user']['user_code'] == code
    with app.app_context():
        user = db.session.get(User, created.json['user']['id'])
        assert user.password_hash != 'correct-horse-battery'


def test_duplicate_normalized_mobile(client):
    signup(client)
    assert signup(client, mobile='+91 98765 43210').status_code == 409


@pytest.mark.parametrize('data', [{'role': 'admin'}, {'mobile': '123'}, {'mobile': 123}, {'mobile': {}}, {'password': 'short'}, {'name': ''}, {'name': 123}])
def test_registration_validation(client, data):
    assert signup(client, **data).status_code == 400


def test_generic_login_failures_and_disabled_account(client, app):
    created = signup(client)
    wrong = signin(client, password='wrong')
    unknown = signin(client, mobile='+14155552671')
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json == unknown.json
    token = signin(client)
    with app.app_context():
        db.session.get(User, created.json['user']['id']).status = 'disabled'
        db.session.commit()
    assert signin(client).status_code == 401
    assert client.get('/api/v1/me', headers=headers(token)).status_code == 401


def test_role_authorization_and_pending_driver(client):
    signup(client)
    rider = headers(signin(client))
    assert client.get('/api/v1/admin/overview', headers=rider).status_code == 403
    assert client.get('/api/v1/driver/overview', headers=rider).status_code == 403
    signup(client, mobile='+14155552671', role='driver')
    driver = headers(signin(client, mobile='+14155552671'))
    response = client.get('/api/v1/driver/overview', headers=driver)
    assert response.status_code == 200 and response.json['approval'] == 'pending'
    assert response.json['availability_enabled'] is False
    assert client.get('/api/v1/admin/overview', headers=driver).status_code == 403


def test_protected_admin_provisioning(client, app):
    with app.app_context():
        register({'name': 'Admin', 'mobile': '+14155552671', 'password': 'correct-horse-battery', 'role': 'admin'}, allow_admin=True)
    admin = headers(signin(client, mobile='+14155552671'))
    assert client.get('/api/v1/admin/overview', headers=admin).status_code == 200


def test_expired_invalid_missing_tokens(client, app):
    signup(client)
    now = datetime.now(timezone.utc)
    token = jwt.encode({'sub': '1', 'iat': now-timedelta(hours=1), 'exp': now-timedelta(minutes=1)}, app.config['JWT_SECRET'], algorithm='HS256')
    for header in ({}, {'Authorization': 'Bearer broken'}, {'Authorization': f'Bearer {token}'}):
        assert client.get('/api/v1/me', headers=header).status_code == 401


def test_auth_rate_limit(client):
    for _ in range(10):
        assert client.post('/api/v1/auth/login', json={}).status_code == 401
    assert client.post('/api/v1/auth/login', json={}).status_code == 429


def test_json_validation_and_docs(client):
    assert client.post('/api/v1/auth/register', json=[]).status_code == 400
    assert client.post('/api/v1/auth/register', data='bad').status_code == 400
    assert client.get('/api/v1/openapi.json').json['openapi'] == '3.0.3'
    assert client.get('/api/v1/health').json['storage'] == 'sqlite-development'

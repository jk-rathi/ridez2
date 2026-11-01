from time import monotonic
from pathlib import Path
import pytest
from sqlalchemy import text
from app import create_app, db
from test_auth import app, client


def test_production_frontend_deep_links_and_api_boundaries(app,client,tmp_path):
    (tmp_path/'assets').mkdir()
    (tmp_path/'index.html').write_text('<html>ridez production</html>')
    (tmp_path/'assets'/'app-test.js').write_text('console.log("built");')
    app.config['FRONTEND_DIST']=str(tmp_path)
    for path in ('/','/login','/rider/history','/driver/account','/admin/drivers'):
        response=client.get(path)
        assert response.status_code==200 and b'ridez production' in response.data
        assert response.headers['Cache-Control']=='no-cache'
    asset=client.get('/assets/app-test.js')
    assert asset.status_code==200 and 'immutable' in asset.headers['Cache-Control']
    for path in ('/assets/missing.js','/api/v1/missing','/socket.io/missing','/.env','/../requirements.lock'):
        response=client.get(path)
        assert response.status_code==(400 if path.startswith('/socket.io/') else 404) and b'ridez production' not in response.data
    assert client.get('/api/v1/me').status_code==401
    assert asset.headers['X-Content-Type-Options']=='nosniff'


def test_readiness_requires_schema_and_live_matching_worker(app,client):
    assert client.get('/api/v1/ready').status_code==503
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config=Config();config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'migrations'))
    head=ScriptDirectory.from_config(config).get_current_head()
    with app.app_context():
        db.session.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
        db.session.execute(text('INSERT INTO alembic_version (version_num) VALUES (:version)'),{'version':head})
        db.session.commit()
    assert client.get('/api/v1/ready').status_code==503
    app.extensions['matching_last_tick']=monotonic()
    assert client.get('/api/v1/ready').json=={'status':'ready','database':True,'matching_worker':True}
    assert client.get('/api/v1/ready').status_code==200
    app.extensions['matching_last_tick']=monotonic()-11
    assert client.get('/api/v1/ready').status_code==503
    with app.app_context():
        db.session.execute(text("UPDATE alembic_version SET version_num='old'"));db.session.commit()
    app.extensions['matching_last_tick']=monotonic()
    assert client.get('/api/v1/ready').status_code==503


def production(monkeypatch,**overrides):
    monkeypatch.setenv('APP_ENV','production')
    config={'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://','JWT_SECRET':'production-jwt-test-only-1234567890123456','USER_CODE_SECRET':'production-code-test-only-12345678901234','GOOGLE_MAPS_SERVER_KEY':'test-server-key-not-for-requests'}
    return create_app(config|overrides)


@pytest.mark.parametrize('overrides',[
    {'JWT_SECRET':'short'}, {'USER_CODE_SECRET':'short'},
    {'JWT_SECRET':'same-key-value-for-tests-only-123456','USER_CODE_SECRET':'same-key-value-for-tests-only-123456'},
    {'GOOGLE_MAPS_SERVER_KEY':''},
])
def test_production_rejects_incomplete_configuration(monkeypatch,overrides):
    with pytest.raises(RuntimeError):production(monkeypatch,**overrides)


def test_render_proxy_secure_cookie_origin_and_headers(monkeypatch):
    app=production(monkeypatch,TRUST_PROXY_HEADERS=True)
    with app.app_context():db.create_all()
    with app.test_client() as client:
        client.post('/api/v1/auth/register',json={'name':'Render test','mobile':'+919876543210','password':'production-test-password'})
        result=client.post('/api/v1/auth/login',base_url='http://ridez-test.onrender.com',headers={'X-Forwarded-Proto':'https','Origin':'https://ridez-test.onrender.com'},json={'mobile':'+919876543210','password':'production-test-password'})
        assert result.status_code==200
        assert 'Secure;' in result.headers['Set-Cookie'] and 'HttpOnly;' in result.headers['Set-Cookie']
        assert result.headers['Strict-Transport-Security']=='max-age=31536000'
        bad=client.post('/api/v1/auth/login',base_url='http://ridez-test.onrender.com',headers={'X-Forwarded-Proto':'https','Origin':'https://evil.example'},json={})
        assert bad.status_code==403
    with app.app_context():db.drop_all()


@pytest.mark.parametrize('missing_config,expected',[
    ({'SQLALCHEMY_DATABASE_URI':None},['DATABASE_URL']),
    ({'JWT_SECRET':''},['JWT_SECRET']),
    ({'USER_CODE_SECRET':'   '},['USER_CODE_SECRET']),
    ({'SQLALCHEMY_DATABASE_URI':'','JWT_SECRET':'','USER_CODE_SECRET':''},['DATABASE_URL','JWT_SECRET','USER_CODE_SECRET']),
])
def test_missing_production_settings_name_only_missing_variables(monkeypatch,missing_config,expected):
    with pytest.raises(RuntimeError) as error:
        production(monkeypatch,**missing_config)
    message=str(error.value)
    assert message.startswith('Missing required environment variables: '+', '.join(expected)+'.')
    assert 'Render service > Environment' in message
    assert 'production-jwt-test-only' not in message and 'production-code-test-only' not in message

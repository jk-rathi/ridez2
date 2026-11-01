from sqlalchemy import select,func
from werkzeug.security import check_password_hash
from app import db
from app.models import User
from app.services import register
from test_auth import app,client


def settings(monkeypatch,**overrides):
    values={'BOOTSTRAP_ADMIN_MOBILE':'+919876543210','BOOTSTRAP_ADMIN_NAME':'Owner Admin',
            'BOOTSTRAP_ADMIN_PASSWORD':'bootstrap-only-test-password'}|overrides
    for key,value in values.items():monkeypatch.setenv(key,value)


def test_bootstrap_creates_admin_and_does_not_log_credentials(app,client,monkeypatch):
    settings(monkeypatch)
    result=app.test_cli_runner().invoke(args=['bootstrap-admin'])
    assert result.exit_code==0 and 'created successfully' in result.output
    assert '+919876543210' not in result.output and 'bootstrap-only-test-password' not in result.output
    login=client.post('/api/v1/auth/login',json={'mobile':'+919876543210','password':'bootstrap-only-test-password'})
    assert login.status_code==200 and login.json['user']['role']=='admin'


def test_restarts_do_not_duplicate_or_reset_existing_admin(app,monkeypatch):
    settings(monkeypatch)
    runner=app.test_cli_runner()
    assert runner.invoke(args=['bootstrap-admin']).exit_code==0
    settings(monkeypatch,BOOTSTRAP_ADMIN_PASSWORD='different-test-password',BOOTSTRAP_ADMIN_NAME='Changed name')
    result=runner.invoke(args=['bootstrap-admin'])
    assert result.exit_code==0 and 'already exists' in result.output
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(User))==1
        user=db.session.scalar(select(User))
        assert user.name=='Owner Admin' and check_password_hash(user.password_hash,'bootstrap-only-test-password')


def test_existing_rider_is_not_promoted_or_replaced(app,monkeypatch):
    settings(monkeypatch)
    with app.app_context():
        register({'name':'Existing rider','mobile':'+919876543210','password':'existing-rider-password'})
    result=app.test_cli_runner().invoke(args=['bootstrap-admin'])
    assert result.exit_code!=0 and 'never promoted' in result.output
    with app.app_context():
        user=db.session.scalar(select(User))
        assert user.role=='rider' and check_password_hash(user.password_hash,'existing-rider-password')


def test_missing_bootstrap_settings_are_named_without_values(app,monkeypatch):
    settings(monkeypatch,BOOTSTRAP_ADMIN_PASSWORD='')
    result=app.test_cli_runner().invoke(args=['bootstrap-admin'])
    assert result.exit_code!=0 and 'BOOTSTRAP_ADMIN_PASSWORD' in result.output
    assert '+919876543210' not in result.output


def test_disabled_admin_is_not_reactivated(app,monkeypatch):
    settings(monkeypatch)
    runner=app.test_cli_runner()
    assert runner.invoke(args=['bootstrap-admin']).exit_code==0
    with app.app_context():
        db.session.scalar(select(User)).status='disabled';db.session.commit()
    result=runner.invoke(args=['bootstrap-admin'])
    assert result.exit_code!=0 and 'does not reactivate' in result.output

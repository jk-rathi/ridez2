from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
import pytest
from sqlalchemy import select, func
from app import create_app, db
from app.models import User, Ride, FareQuote, RevenueLedger, ActiveRide, AdminAudit
from app.services import register
from app.ride_service import now
from test_auth import app, client


@pytest.fixture()
def actors(app):
    result = {}
    with app.app_context():
        for name, mobile, role in [('rider','+919876543210','rider'), ('other','+14155552671','rider'), ('driver','+12025550123','driver'), ('second','+12025550124','driver'), ('admin','+12025550125','admin')]:
            user = register(dict(name=name, mobile=mobile, role=role, password='long-enough-password'), allow_admin=True)
            result[name] = {'id': user.id, 'mobile': mobile}
    with app.test_client() as client:
        for actor in result.values():
            response = client.post('/api/v1/auth/login', json=dict(mobile=actor['mobile'],password='long-enough-password'))
            assert response.status_code == 200
            actor['headers'] = {'Authorization': 'Bearer '+response.json['access_token']}
    return result


def post(client, actors, actor, path, **data):
    return client.post('/api/v1'+path, headers=actors[actor]['headers'], json=data)


def prepare(client, actors, driver='driver'):
    response=post(client,actors,'admin',f"/admin/drivers/{actors[driver]['id']}/approve",reason='Documents reviewed for test')
    assert response.status_code == 200
    assert post(client,actors,driver,'/driver/availability',available=True,latitude=19.076,longitude=72.8777,accuracy_m=10,recorded_at=now().isoformat()+'Z').status_code == 200


def quote(client, actors, rider='rider'):
    response=post(client,actors,rider,'/fares/quotes',pickup='City centre',destination='Riverside',pickup_lat=19.076,pickup_lng=72.8777)
    assert response.status_code == 201
    return response.json['quote']


def book(client, actors, rider='rider'):
    return post(client,actors,rider,'/rides',quote_id=quote(client,actors,rider)['id']).json['ride']


def test_full_ride_and_exactly_once_settlement(client, app, actors):
    prepare(client,actors)
    ride=book(client,actors)
    ride_id=ride['id']
    workspace=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert workspace['invitations'][0]['id'] == ride_id
    assert post(client,actors,'driver',f'/rides/{ride_id}/accept').status_code == 200
    assert post(client,actors,'driver',f'/rides/{ride_id}/accept').status_code == 200
    assert post(client,actors,'driver',f'/rides/{ride_id}/start').status_code == 409
    for action in ['depart','arrive','start','complete']:
        response=post(client,actors,'driver',f'/rides/{ride_id}/{action}', **({'otp': client.get('/api/v1/workspace', headers=actors['rider']['headers']).json['trip_otp']} if action == 'start' else {}))
        assert response.status_code == 200, response.json
    settlement=response.json['ride']['settlement']
    assert Decimal(settlement['driver_amount']) + Decimal(settlement['company_amount']) == Decimal(ride['quote']['total'])
    assert settlement['driver_pct'] == '85.00'
    assert post(client,actors,'driver',f'/rides/{ride_id}/complete').json['ride']['settlement'] == settlement
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger)) == 1
        assert db.session.scalar(select(func.count()).select_from(ActiveRide)) == 0
        assert db.session.scalar(select(func.count()).select_from(AdminAudit)) == 1
    workspace=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert workspace['allocated_earnings'] == settlement['driver_amount']
    assert workspace['available'] is True
    assert len(workspace['rides']) == 1


def test_quote_validation_ownership_expiry_and_idempotent_booking(client, app, actors):
    assert post(client,actors,'rider','/fares/quotes',pickup='Same',destination='same').status_code == 400
    assert post(client,actors,'driver','/fares/quotes',pickup='A',destination='B').status_code == 403
    quoted=quote(client,actors)
    assert post(client,actors,'other','/rides',quote_id=quoted['id']).status_code == 404
    first=post(client,actors,'rider','/rides',quote_id=quoted['id'])
    second=post(client,actors,'rider','/rides',quote_id=quoted['id'])
    assert first.json['ride']['id'] == second.json['ride']['id']
    assert post(client,actors,'rider','/rides',quote_id=quote(client,actors)['id']).status_code == 409
    assert post(client,actors,'rider',f"/rides/{first.json['ride']['id']}/cancel").status_code == 200
    expired=quote(client,actors)
    with app.app_context():
        db.session.get(FareQuote,expired['id']).expires_at=now()-timedelta(seconds=1)
        db.session.commit()
    assert post(client,actors,'rider','/rides',quote_id=expired['id']).status_code == 409


def test_expired_invitation_rejection_and_cancel(client, app, actors):
    app.config['MATCH_MAX_RADIUS_M']=500
    prepare(client,actors)
    ride=book(client,actors)
    with app.app_context():
        db.session.get(Ride,ride['id']).expires_at=now()
        db.session.commit()
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code == 409
    workspace=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json
    assert workspace['active_ride'] is None
    assert workspace['rides'][0]['status'] == 'NO_DRIVER_FOUND'
    ride=book(client,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/reject").status_code == 200
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code == 409
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel").status_code == 200
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel").status_code == 200


def test_permissions_and_pending_driver(client, actors):
    assert post(client,actors,'driver','/driver/availability',available=True).status_code == 403
    assert post(client,actors,'rider',f"/admin/drivers/{actors['driver']['id']}/approve",reason='no').status_code == 403
    prepare(client,actors)
    ride=book(client,actors)
    assert client.get('/api/v1/rides/'+ride['id'],headers=actors['other']['headers']).status_code == 404
    assert post(client,actors,'second',f"/rides/{ride['id']}/accept").status_code == 404
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code == 200
    assert post(client,actors,'rider',f"/rides/{ride['id']}/complete").status_code == 403
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel").status_code == 400
    assert post(client,actors,'driver','/driver/availability',available=False).status_code == 200


def test_simulator_disabled(client, app, actors):
    app.config['SIMULATOR_ENABLED']=False
    assert post(client,actors,'rider','/fares/quotes',pickup='A',destination='B').status_code == 503
    assert post(client,actors,'rider','/rides',quote_id='anything').status_code == 503


def test_second_ride_acceptance_reports_conflict_after_driver_becomes_busy(client,actors):
    prepare(client,actors)
    first=book(client,actors)
    second=book(client,actors,'other')
    assert post(client,actors,'driver',f"/rides/{first['id']}/accept").status_code==200
    response=post(client,actors,'driver',f"/rides/{second['id']}/accept")
    assert response.status_code==409 and 'active trip' in response.json['error']


@pytest.mark.parametrize('same_driver',[False,True])
def test_concurrent_acceptance_has_one_winner(tmp_path, same_driver):
    concurrent_app=create_app({'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,'TESTING':True,'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "race.db"}', 'JWT_SECRET':'concurrent-test-jwt-key-1234567890','USER_CODE_SECRET':'concurrent-test-code-key-1234567890'})
    with concurrent_app.app_context():
        db.create_all()
    people=actors.__wrapped__(concurrent_app)
    with concurrent_app.test_client() as client:
        prepare(client,people)
        prepare(client,people,'second')
        first=book(client,people)
        second=book(client,people,'other') if same_driver else first
    barrier=Barrier(2)
    def attempt(name,ride):
        with concurrent_app.test_client() as client:
            barrier.wait(timeout=5)
            return post(client,people,name,f"/rides/{ride['id']}/accept").status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        a=executor.submit(attempt,'driver',first)
        b=executor.submit(attempt,'driver' if same_driver else 'second',second)
        assert sorted([a.result(),b.result()]) == [200,409]
    with concurrent_app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Ride).where(Ride.status=='ASSIGNED')) == 1
        assert db.session.scalar(select(func.count()).select_from(ActiveRide).join(User,User.id==ActiveRide.user_id).where(User.role=='driver')) == 1

from sqlalchemy import select,func
import pytest
from app import db
from app.models import AdminAudit
from test_auth import app,client
from test_rides import actors,prepare,book,post


def save(client,actors,**changes):
    data=dict(version=0,registration='mh 12 ab 1234',model='Maruti Suzuki Dzire',color='White',reason='Reviewed registration and vehicle')|changes
    return client.put(f"/api/v1/admin/drivers/{actors['driver']['id']}/vehicle",headers=actors['admin']['headers'],json=data)


def test_vehicle_saved_and_shown_on_assigned_ride(client,app,actors):
    result=save(client,actors)
    assert result.status_code==200,result.json
    assert result.json['user']['vehicle']==dict(registration='MH 12 AB 1234',model='Maruti Suzuki Dzire',color='White',version=1)
    prepare(client,actors)
    ride=book(client,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code==200
    for role in ('rider','driver','admin'):
        response=client.get('/api/v1/rides/'+ride['id'],headers=actors[role]['headers'])
        assert response.json['ride']['driver']['vehicle']==dict(registration='MH 12 AB 1234',model='Maruti Suzuki Dzire',color='White')
        if role=='rider':
            assert 'mobile' not in response.json['ride']['driver']
            assert 'settlement' not in response.json['ride']
    assert save(client,actors,version=1,registration='MH 01 CD 5678').status_code==409
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(AdminAudit).where(AdminAudit.action=='driver.vehicle.updated'))==1


def test_future_vehicle_changes_do_not_rewrite_trip_history(client,actors):
    assert save(client,actors).status_code==200
    prepare(client,actors)
    ride=book(client,actors)
    otp=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']
    for action in ('accept','depart','arrive','start','complete'):
        assert post(client,actors,'driver',f"/rides/{ride['id']}/{action}",**({'otp':otp} if action=='start' else {})).status_code==200
    assert save(client,actors,version=1,registration='MH 01 CD 5678',model='Hyundai Aura',color='Silver').status_code==200
    history=client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']).json['ride']
    assert history['driver']['vehicle']['registration']=='MH 12 AB 1234'
    assert save(client,actors,version=1).status_code==409
    listing=client.get('/api/v1/admin/drivers',headers=actors['admin']['headers']).json['items']
    assert next(row for row in listing if row['id']==actors['driver']['id'])['vehicle']['registration']=='MH 01 CD 5678'


@pytest.mark.parametrize('changes',[{'registration':''},{'registration':'<script>'},{'registration':'A'*21},{'model':''},{'color':' '},{'reason':''},{'version':True},{'version':-1}])
def test_vehicle_validation(client,actors,changes):
    assert save(client,actors,**changes).status_code==400


def test_vehicle_admin_only_and_audited(client,actors):
    path=f"/api/v1/admin/drivers/{actors['driver']['id']}/vehicle"
    for role in ('rider','driver'):
        assert client.put(path,headers=actors[role]['headers'],json={}).status_code==403
    assert save(client,actors).status_code==200
    items=client.get('/api/v1/admin/audit?q=driver.vehicle.updated',headers=actors['admin']['headers']).json['items']
    assert len(items)==1
    details=client.get('/api/v1/admin/audit/driver/'+items[0]['id'],headers=actors['admin']['headers']).json
    assert details['changes'][0]==dict(field='Car number',before='Not provided',after='MH 12 AB 1234')


def test_missing_vehicle_is_explicit_and_not_fabricated(client,actors):
    prepare(client,actors)
    ride=book(client,actors)
    accepted=post(client,actors,'driver',f"/rides/{ride['id']}/accept")
    assert accepted.json['ride']['driver']['vehicle'] is None


def test_vehicle_edit_and_acceptance_keep_one_consistent_car(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app import create_app
    race=create_app({'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
        'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "vehicle-race.db"}',
        'JWT_SECRET':'vehicle-race-test-only-secret-123456','USER_CODE_SECRET':'vehicle-race-code-secret-123456'})
    with race.app_context():db.create_all()
    people=actors.__wrapped__(race)
    with race.test_client() as device:
        assert save(device,people).status_code==200
        prepare(device,people)
        ride=book(device,people)
    barrier=Barrier(2)
    def accept():
        with race.test_client() as device:
            barrier.wait(timeout=5)
            return post(device,people,'driver',f"/rides/{ride['id']}/accept").status_code
    def edit():
        with race.test_client() as device:
            barrier.wait(timeout=5)
            return save(device,people,version=1,registration='MH 01 CD 5678').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        acceptance=pool.submit(accept);change=pool.submit(edit)
        assert acceptance.result()==200
        changed=change.result();assert changed in (200,409)
    with race.test_client() as device:
        details=device.get('/api/v1/rides/'+ride['id'],headers=people['rider']['headers']).json['ride']
        assert details['driver']['vehicle']['registration']==('MH 01 CD 5678' if changed==200 else 'MH 12 AB 1234')

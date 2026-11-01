from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from sqlalchemy import select,func
import pytest
from app import create_app, db
from app.models import DriverLocation, DriverPresence, ActiveRide, RevenueLedger
from app.location_service import utcnow
from test_auth import app,client
from test_rides import actors,prepare,book,post


def underway(client,actors):
    prepare(client,actors)
    ride=book(client,actors)
    otp=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']
    for action in ('accept','depart','arrive','start'):
        assert post(client,actors,'driver',f"/rides/{ride['id']}/{action}",**({'otp':otp} if action=='start' else {})).status_code==200
    return ride


def finish(client,actors,ride):
    return post(client,actors,'driver',f"/rides/{ride['id']}/complete")


def workspace(client,actors):
    return client.get('/api/v1/workspace',headers=actors['driver']['headers']).json


def test_fresh_active_driver_stays_available_and_can_accept_next_ride(client,actors):
    first=underway(client,actors)
    assert finish(client,actors,first).status_code==200
    state=workspace(client,actors)
    assert state['available'] and state['resume_available'] and state['active_ride'] is None
    second=book(client,actors)
    state=workspace(client,actors)
    assert any(ride['id']==second['id'] for ride in state['invitations'])
    assert post(client,actors,'driver',f"/rides/{second['id']}/accept").status_code==200


def test_choose_offline_during_trip_persists_and_stops_auto_availability(client,app,actors):
    ride=underway(client,actors)
    result=post(client,actors,'driver','/driver/availability',available=False)
    assert result.json==dict(available=False,resume_available=False,active_trip=True)
    state=workspace(client,actors)
    assert state['active_ride']['id']==ride['id'] and not state['resume_available']
    assert finish(client,actors,ride).status_code==200
    assert not workspace(client,actors)['available']
    # Retrying completion must not override an explicit offline choice.
    assert finish(client,actors,ride).status_code==200
    assert not workspace(client,actors)['available']


def test_reenable_next_trip_choice_requires_fresh_location(client,actors):
    ride=underway(client,actors)
    assert post(client,actors,'driver','/driver/availability',available=False).status_code==200
    assert post(client,actors,'driver','/driver/availability',available=True).status_code==400
    result=post(client,actors,'driver','/driver/availability',available=True,latitude=19.076,longitude=72.8777,accuracy_m=10,recorded_at=utcnow().isoformat()+'Z')
    assert result.status_code==200 and result.json['resume_available'] and not result.json['available']
    assert finish(client,actors,ride).status_code==200
    assert workspace(client,actors)['available']


@pytest.mark.parametrize('condition',['stale','suspended','simulator_disabled','logout'])
def test_completion_does_not_reactivate_ineligible_driver(client,app,actors,condition):
    ride=underway(client,actors)
    if condition=='stale':
        with app.app_context():
            db.session.get(DriverLocation,actors['driver']['id']).recorded_at=utcnow()-timedelta(seconds=91)
            db.session.commit()
    elif condition=='suspended':
        assert post(client,actors,'admin',f"/admin/drivers/{actors['driver']['id']}/suspend",version=1,reason='Review pending').status_code==200
    elif condition=='simulator_disabled':app.config['SIMULATOR_ENABLED']=False
    else:
        # Another device can still finish an assigned trip, but logout must keep new work paused.
        other=app.test_client()
        signed=other.post('/api/v1/auth/login',json={'mobile':actors['driver']['mobile'],'password':'long-enough-password'})
        assert signed.status_code==200
        assert other.post('/api/v1/auth/logout',headers={'X-Session-Request':'1'}).status_code==200
    assert finish(client,actors,ride).status_code==200
    state=workspace(client,actors)
    assert not state['available'] and state['active_ride'] is None
    assert state['earnings']


def test_complete_retry_does_not_restore_availability_after_manual_offline(client,app,actors):
    ride=underway(client,actors)
    assert finish(client,actors,ride).status_code==200
    assert workspace(client,actors)['available']
    assert post(client,actors,'driver','/driver/availability',available=False).status_code==200
    assert finish(client,actors,ride).status_code==200
    assert not workspace(client,actors)['available']
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger))==1
        assert db.session.scalar(select(func.count()).select_from(ActiveRide))==0


@pytest.mark.parametrize('operation',['offline','logout'])
def test_offline_and_completion_race_always_finishes_offline(tmp_path,operation):
    race=create_app({'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
        'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "availability-race.db"}',
        'JWT_SECRET':'auto-availability-test-key-123456789','USER_CODE_SECRET':'auto-availability-code-key-123456789'})
    with race.app_context():db.create_all()
    people=actors.__wrapped__(race)
    with race.test_client() as device:ride=underway(device,people)
    logout_device=race.test_client()
    if operation=='logout':
        assert logout_device.post('/api/v1/auth/login',json={'mobile':people['driver']['mobile'],'password':'long-enough-password'}).status_code==200
    barrier=Barrier(2)
    def complete():
        with race.test_client() as device:
            barrier.wait(timeout=5)
            return finish(device,people,ride).status_code
    def offline():
        with race.test_client() as device:
            barrier.wait(timeout=5)
            if operation=='logout':
                return logout_device.post('/api/v1/auth/logout',headers={'X-Session-Request':'1'}).status_code
            return post(device,people,'driver','/driver/availability',available=False).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        completion=pool.submit(complete);choice=pool.submit(offline)
        assert completion.result()==choice.result()==200
    with race.app_context():
        presence=db.session.get(DriverPresence,people['driver']['id'])
        assert not presence.available and not presence.resume_available
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger))==1

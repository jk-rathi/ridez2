from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from sqlalchemy import select,func
import pytest
from app import create_app, db
from app.models import Ride, ActiveRide, Invitation, DriverPresence, RevenueLedger, MatchRound
from app.ride_service import now
from test_auth import app,client
from test_rides import actors,prepare,book,post


def assigned(client,actors,phase='ASSIGNED'):
    prepare(client,actors)
    ride=book(client,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code==200
    for action in {'ASSIGNED':[],'ARRIVING':['depart'],'WAITING':['depart','arrive'],'IN_PROGRESS':['depart','arrive','start']}[phase]:
        payload={'otp':client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']} if action=='start' else {}
        assert post(client,actors,'driver',f"/rides/{ride['id']}/{action}",**payload).status_code==200
    return ride


@pytest.mark.parametrize('phase',['ASSIGNED','ARRIVING','WAITING'])
@pytest.mark.parametrize('actor',['rider','driver'])
def test_pretrip_cancellation_releases_both_participants(client,app,actors,phase,actor):
    ride=assigned(client,actors,phase)
    response=post(client,actors,actor,f"/rides/{ride['id']}/cancel",reason='Plans changed for this test')
    assert response.status_code==200,response.json
    cancelled=response.json['ride']
    assert cancelled['status']=='CANCELLED' and cancelled['cancellation']['by']==actor
    assert cancelled['cancellation']['by_you']
    assert cancelled['cancellation']['reason']=='Plans changed for this test'
    assert cancelled['cancellation']['cancelled_at']
    repeat=post(client,actors,actor,f"/rides/{ride['id']}/cancel",reason='Different retry reason')
    assert repeat.json['ride']['cancellation']==cancelled['cancellation']
    for role in ('rider','driver'):
        data=client.get('/api/v1/workspace',headers=actors[role]['headers']).json
        assert data['active_ride'] is None
        assert data['recent_cancellation']['by']==actor
        assert data['recent_cancellation']['by_you']==(role==actor)
        assert data['rides'][0]['cancellation']['reason']=='Plans changed for this test'
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(ActiveRide))==0
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger))==0
        assert not db.session.get(DriverPresence,actors['driver']['id']).available
        record=db.session.get(Ride,ride['id'])
        assert record.cancelled_by==actors[actor]['id'] and record.cancelled_at
        assert db.session.get(MatchRound,(ride['id'],1)).outcome=='ASSIGNED'
    assert post(client,actors,'driver',f"/rides/{ride['id']}/start",otp='123456').status_code==409
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code!=200
    metrics=client.get('/api/v1/workspace',headers=actors['admin']['headers']).json['metrics']
    assert metrics['cancelled_rides']==1 and metrics['active_rides']==0
    # The cancelled quote remains an idempotency key, not a new booking.
    old=post(client,actors,'rider','/rides',quote_id=ride['quote']['id']).json['ride']
    assert old['id']==ride['id'] and old['status']=='CANCELLED'
    assert book(client,actors)['id']!=ride['id']


def test_search_cancel_keeps_unassigned_drivers_available(client,app,actors):
    prepare(client,actors)
    ride=book(client,actors)
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel",reason='Pickup changed').status_code==200
    with app.app_context():
        assert db.session.get(DriverPresence,actors['driver']['id']).available
        assert db.session.get(Invitation,(ride['id'],actors['driver']['id'])).status=='CLOSED'
        assert db.session.get(MatchRound,(ride['id'],1)).outcome=='CANCELLED'
    assert client.get('/api/v1/workspace',headers=actors['driver']['headers']).json['recent_cancellation'] is None


@pytest.mark.parametrize('reason',[None,'','   ',42,'x'*301])
def test_assigned_cancel_requires_valid_reason(client,actors,reason):
    ride=assigned(client,actors)
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel",reason=reason).status_code==400
    assert client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']).json['ride']['status']=='ASSIGNED'


def test_midtrip_and_unauthorized_cancellation_are_rejected(client,actors):
    ride=assigned(client,actors,'IN_PROGRESS')
    for role in ('rider','driver'):
        assert post(client,actors,role,f"/rides/{ride['id']}/cancel",reason='No longer pretrip').status_code==409
    for role in ('other','second'):
        assert post(client,actors,role,f"/rides/{ride['id']}/cancel",reason='Unrelated user').status_code==404
    assert post(client,actors,'admin',f"/rides/{ride['id']}/cancel",reason='Not an incident action').status_code==403
    assert post(client,actors,'driver',f"/rides/{ride['id']}/complete").status_code==200
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel",reason='Already completed').status_code==409


def test_recent_notice_expires_but_history_is_preserved(client,app,actors):
    ride=assigned(client,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/cancel",reason='Vehicle issue').status_code==200
    with app.app_context():
        db.session.get(Ride,ride['id']).cancelled_at=now()-timedelta(minutes=11)
        db.session.commit()
    for role in ('rider','driver'):
        data=client.get('/api/v1/workspace',headers=actors[role]['headers']).json
        assert data['recent_cancellation'] is None
        assert data['rides'][0]['cancellation']['reason']=='Vehicle issue'


def test_legacy_cancel_record_does_not_invent_actor_or_time(client,app,actors):
    ride=book(client,actors)
    with app.app_context():
        db.session.get(Ride,ride['id']).status='CANCELLED'
        db.session.commit()
    details=client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']).json['ride']['cancellation']
    assert details==dict(by=None,by_you=False,reason='Reason was not recorded',cancelled_at=None)


@pytest.mark.parametrize('operation',['accept','start'])
def test_cancel_race_has_one_valid_outcome(tmp_path,operation):
    race=create_app({'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
        'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "cancel-race.db"}',
        'JWT_SECRET':'cancel-race-test-only-secret-123456','USER_CODE_SECRET':'cancel-race-code-secret-123456'})
    with race.app_context():db.create_all()
    people=actors.__wrapped__(race)
    with race.test_client() as device:
        if operation=='accept':
            prepare(device,people);ride=book(device,people)
        else:ride=assigned(device,people,'WAITING')
        otp=device.get('/api/v1/workspace',headers=people['rider']['headers']).json['trip_otp']
    barrier=Barrier(2)
    def cancel():
        with race.test_client() as device:
            barrier.wait(timeout=5)
            return post(device,people,'rider',f"/rides/{ride['id']}/cancel",reason='Concurrent rider cancellation').status_code
    def progress():
        with race.test_client() as device:
            barrier.wait(timeout=5)
            return post(device,people,'driver',f"/rides/{ride['id']}/{operation}",**({'otp':otp} if operation=='start' else {})).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancellation=pool.submit(cancel);advancement=pool.submit(progress)
        results=(cancellation.result(),advancement.result())
    assert 200 in results and all(status in (200,403,409) for status in results)
    with race.app_context():
        record=db.session.get(Ride,ride['id'])
        claims=db.session.scalar(select(func.count()).select_from(ActiveRide))
        if record.status=='CANCELLED':
            assert claims==0 and record.cancelled_by==people['rider']['id']
        else:
            assert record.status==('ASSIGNED' if operation=='accept' else 'IN_PROGRESS')
            assert claims==2 and record.cancelled_at is None
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger))==0


def test_expired_search_cannot_be_relabelled_as_cancelled(client,app,actors):
    app.config['MATCH_MAX_RADIUS_M']=500
    ride=book(client,actors)
    with app.app_context():
        db.session.get(Ride,ride['id']).expires_at=now()-timedelta(seconds=1)
        db.session.commit()
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel",reason='Too late').status_code==409
    with app.app_context():
        record=db.session.get(Ride,ride['id'])
        assert record.status=='NO_DRIVER_FOUND' and record.cancelled_at is None
        assert db.session.scalar(select(func.count()).select_from(ActiveRide))==0


def test_driver_notice_uses_cancellation_time_not_request_order(client,app,actors):
    completed=assigned(client,actors,'IN_PROGRESS')
    assert post(client,actors,'driver',f"/rides/{completed['id']}/complete").status_code==200
    current=assigned(client,actors)
    with app.app_context():
        db.session.get(Ride,current['id']).requested_at=now()-timedelta(minutes=4)
        db.session.commit()
    assert post(client,actors,'rider',f"/rides/{current['id']}/cancel",reason='Latest activity cancelled').status_code==200
    data=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert data['recent_cancellation']['ride_id']==current['id']
    assert data['recent_cancellation']['reason']=='Latest activity cancelled'

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sqlalchemy import select, func
import pytest
from app import create_app, db
from app.models import User, DriverPresence, Invitation, ActiveRide, Ride, AdminAudit
from app.ride_service import now
from app.realtime import socketio, dispatch
from test_auth import app, client
from test_rides import actors, prepare, book, post


def review(client,actors,action,version,**overrides):
    return post(client,actors,'admin',f"/admin/drivers/{actors['driver']['id']}/{action}",version=version,reason='Documents reviewed for '+action,**overrides)


def test_suspend_reinstate_blocks_new_rides_and_preserves_sessions(client,app,actors):
    prepare(client,actors)
    ride=book(client,actors)
    socket=socketio.test_client(app,auth={'token':actors['driver']['headers']['Authorization'][7:]})
    response=review(client,actors,'suspend',1)
    assert response.status_code==200
    assert response.json['user']['status']=='suspended' and response.json['user']['status_revision']==2
    assert review(client,actors,'suspend',1).status_code==200
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(AdminAudit))==2
        assert not db.session.get(DriverPresence,actors['driver']['id']).available
        assert db.session.get(Invitation,(ride['id'],actors['driver']['id'])).status=='CLOSED'
        dispatch()
    assert socket.is_connected() and socket.get_received()
    workspace=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert workspace['user']['status']=='suspended'
    assert workspace['invitations']==[] and not workspace['available']
    assert workspace['suspension']['reason']=='Documents reviewed for suspend'
    assert post(client,actors,'driver','/driver/availability',available=True).status_code==403
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code==403
    signed=client.post('/api/v1/auth/login',json={'mobile':actors['driver']['mobile'],'password':'long-enough-password'})
    assert signed.status_code==200 and signed.json['user']['status']=='suspended'
    assert client.post('/api/v1/auth/refresh',headers={'X-Session-Request':'1'}).status_code==200
    assert review(client,actors,'reinstate',2).status_code==200
    assert review(client,actors,'reinstate',2).status_code==200
    workspace=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert workspace['user']['status']=='active' and not workspace['available'] and not workspace['invitations']
    assert 'suspension' not in workspace
    assert post(client,actors,'driver','/driver/availability',available=True).status_code==400
    assert review(client,actors,'suspend',1).status_code==409  # old retry cannot suspend after reinstatement
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(AdminAudit))==3
    socket.disconnect()


@pytest.mark.parametrize('before',[(),('depart','arrive'),('depart','arrive','start')])
def test_suspension_preserves_trip_tracking_otp_completion_and_earnings(client,app,actors,before):
    prepare(client,actors)
    ride=book(client,actors)
    path=f"/rides/{ride['id']}"
    assert post(client,actors,'driver',path+'/accept').status_code==200
    otp=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']
    for action in before:
        assert post(client,actors,'driver',path+'/'+action,**({'otp':otp} if action=='start' else {})).status_code==200
    assert review(client,actors,'suspend',1).status_code==200
    with app.app_context():
        assert db.session.get(ActiveRide,actors['driver']['id']).ride_id==ride['id']
    assert client.put('/api/v1/driver/location',headers=actors['driver']['headers'],json=dict(latitude=19.076,longitude=72.8777,accuracy_m=10,recorded_at=now().isoformat()+'Z')).status_code==200
    assert post(client,actors,'driver','/driver/availability',available=True).status_code==403
    for action in ('depart','arrive','start','complete')[len(before):]:
        if action=='start':
            assert post(client,actors,'driver',path+'/start',otp='bad').status_code==400
        response=post(client,actors,'driver',path+'/'+action,**({'otp':otp} if action=='start' else {}))
        assert response.status_code==200,response.json
    assert response.json['ride']['settlement']['driver_pct']=='85.00'
    data=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert data['active_ride'] is None and not data['available'] and data['earnings']
    rider=client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']).json['ride']
    assert rider['status']=='COMPLETED' and 'settlement' not in rider
    assert client.put('/api/v1/driver/location',headers=actors['driver']['headers'],json={}).status_code==403


@pytest.mark.parametrize('version',[None,-1,True,1.0,'1'])
def test_status_version_validation(client,actors,version):
    prepare(client,actors)
    assert review(client,actors,'suspend',version).status_code==400


@pytest.mark.parametrize('reason',[None,'','   ',123,'x'*301])
def test_review_reason_validation(client,actors,reason):
    prepare(client,actors)
    response=post(client,actors,'admin',f"/admin/drivers/{actors['driver']['id']}/suspend",version=1,reason=reason)
    assert response.status_code==400


def test_permissions_invalid_targets_and_disabled_pending_guards(client,app,actors):
    for role in ('rider','driver','second'):
        assert client.get('/api/v1/admin/drivers',headers=actors[role]['headers']).status_code==403
        for action in ('suspend','reinstate'):
            assert post(client,actors,role,f"/admin/drivers/{actors['driver']['id']}/{action}",version=0,reason='No permission').status_code==403
    assert review(client,actors,'suspend',0).status_code==409
    assert review(client,actors,'reinstate',0).status_code==409
    assert post(client,actors,'admin',f"/admin/drivers/{actors['rider']['id']}/suspend",version=0,reason='Invalid target').status_code==404
    with app.app_context():
        db.session.get(User,actors['driver']['id']).status='disabled'
        db.session.commit()
    assert review(client,actors,'reinstate',0).status_code==409
    assert review(client,actors,'approve',0).status_code==409


def test_status_change_audit_snapshots_stay_immutable(client,actors):
    prepare(client,actors)
    assert review(client,actors,'suspend',1).status_code==200
    assert review(client,actors,'reinstate',2).status_code==200
    history=client.get('/api/v1/admin/audit?category=driver',headers=actors['admin']['headers']).json
    assert history['total']==3
    expected={'driver.approved':('Pending','Active'),'driver.suspended':('Active','Suspended'),'driver.reinstated':('Suspended','Active')}
    for row in history['items']:
        detail=client.get('/api/v1/admin/audit/driver/'+row['id'],headers=actors['admin']['headers']).json
        before,after=expected[row['action']]
        assert detail['changes']==[{'field':'Account status','before':before,'after':after}]
    assert client.get('/api/v1/admin/audit?q=driver.suspended',headers=actors['admin']['headers']).json['total']==1
    assert client.get('/api/v1/workspace',headers=actors['admin']['headers']).json['metrics']['suspended_drivers']==0


def test_driver_search_filters_pagination_and_literal_wildcards(client,app,actors):
    prepare(client,actors)
    assert review(client,actors,'suspend',1).status_code==200
    def listing(**params):
        return client.get('/api/v1/admin/drivers',headers=actors['admin']['headers'],query_string=params)
    suspended=listing(status='suspended').json
    assert suspended['total']==1 and suspended['items'][0]['id']==actors['driver']['id']
    assert suspended['items'][0]['status_revision']==2
    assert listing(q=actors['driver']['mobile']).json['total']==1
    assert listing(q='%').json['total']==0
    with app.app_context():
        for i in range(25):
            db.session.add(User(name=f'Paged driver {i}',mobile=f'+1999000{i:04d}',password_hash='not-a-login',user_code=f'DRV-PAGED-{i}',role='driver',status='pending'))
        db.session.commit()
    first,second=listing().json,listing(page=2).json
    assert first['total']==second['total']==27
    assert len(first['items'])==20 and len(second['items'])==7
    assert not ({row['id'] for row in first['items']}&{row['id'] for row in second['items']})
    assert listing(status='anything').status_code==400
    assert listing(page='bad').status_code==400
    assert listing(q='x'*101).status_code==400


def test_two_admins_cannot_apply_same_version_concurrently(tmp_path):
    concurrent=create_app({'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
        'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "reviews.db"}',
        'JWT_SECRET':'review-test-only-secret-1234567890','USER_CODE_SECRET':'review-code-test-secret-1234567890'})
    with concurrent.app_context():db.create_all()
    people=actors.__wrapped__(concurrent)
    with concurrent.test_client() as device:prepare(device,people)
    barrier=Barrier(2)
    def attempt(reason):
        with concurrent.test_client() as device:
            barrier.wait(timeout=5)
            return post(device,people,'admin',f"/admin/drivers/{people['driver']['id']}/suspend",version=1,reason=reason).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(attempt,reason) for reason in ('First review','Second review')]
        assert sorted(future.result() for future in futures)==[200,409]
    with concurrent.app_context():
        assert db.session.get(User,people['driver']['id']).status_revision==2
        assert db.session.scalar(select(func.count()).select_from(AdminAudit).where(AdminAudit.action=='driver.suspended'))==1


@pytest.mark.parametrize('operation',['accept','available'])
def test_suspension_serializes_with_new_work(tmp_path,operation):
    concurrent=create_app({'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,
        'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "suspend-race.db"}',
        'JWT_SECRET':'suspend-race-test-secret-1234567890','USER_CODE_SECRET':'suspend-race-code-secret-1234567890'})
    with concurrent.app_context():db.create_all()
    people=actors.__wrapped__(concurrent)
    with concurrent.test_client() as device:
        prepare(device,people)
        ride=book(device,people)
    barrier=Barrier(2)
    def suspend():
        with concurrent.test_client() as device:
            barrier.wait(timeout=5)
            return review(device,people,'suspend',1).status_code
    def work():
        with concurrent.test_client() as device:
            barrier.wait(timeout=5)
            if operation=='accept':return post(device,people,'driver',f"/rides/{ride['id']}/accept").status_code
            return post(device,people,'driver','/driver/availability',available=True,latitude=19.076,longitude=72.8777,accuracy_m=10,recorded_at=now().isoformat()+'Z').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        suspension=pool.submit(suspend)
        attempt=pool.submit(work)
        assert suspension.result()==200
        assert attempt.result() in (200,403,409)
    with concurrent.app_context():
        assert db.session.get(User,people['driver']['id']).status=='suspended'
        assert not db.session.get(DriverPresence,people['driver']['id']).available
        invitation=db.session.get(Invitation,(ride['id'],people['driver']['id']))
        assert invitation.status!='PENDING'
        assigned=db.session.get(ActiveRide,people['driver']['id'])
        if assigned:assert db.session.get(Ride,assigned.ride_id).driver_id==people['driver']['id']


def test_matching_rechecks_stale_candidates_after_suspension_and_reinstatement(client,app,actors):
    from unittest.mock import patch
    from types import SimpleNamespace
    prepare(client,actors)
    assert review(client,actors,'suspend',1).status_code==200
    stale=[SimpleNamespace(driver_id=actors['driver']['id'])]
    with patch('app.ride_repository.eligible_drivers',return_value=stale):
        first=book(client,actors)
    with app.app_context():
        assert db.session.get(Invitation,(first['id'],actors['driver']['id'])) is None
    assert post(client,actors,'rider',f"/rides/{first['id']}/cancel").status_code==200
    assert review(client,actors,'reinstate',2).status_code==200
    # Reinstatement alone must not make an old candidate available again.
    with patch('app.ride_repository.eligible_drivers',return_value=stale):
        second=book(client,actors)
    with app.app_context():
        assert db.session.get(Invitation,(second['id'],actors['driver']['id'])) is None

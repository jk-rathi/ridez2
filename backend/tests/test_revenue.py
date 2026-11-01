from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from threading import Barrier
from unittest.mock import patch
from sqlalchemy import select, func
import pytest
from app import create_app, db
from app.models import RevenueLedger, RevenueShareSetting, FareQuote
from app import revenue_service
from app.location_service import utcnow
from test_auth import app, client
from test_rides import actors, prepare, book, post


def save(client,actors,**overrides):
    return client.put('/api/v1/admin/revenue-share',headers=actors['admin']['headers'],json=dict(version=0,driver_pct='80.00',company_pct='20.00',reason='Reviewed driver allocation',effective_from=None)|overrides)


def in_progress(client,actors):
    prepare(client,actors)
    ride=book(client,actors)
    for action in ('accept','depart','arrive','start'):
        response=post(client,actors,'driver',f"/rides/{ride['id']}/{action}", **({'otp': client.get('/api/v1/workspace', headers=actors['rider']['headers']).json['trip_otp']} if action == 'start' else {}))
        assert response.status_code==200,response.json
    return ride


def test_default_and_admin_permissions(client,actors):
    data=client.get('/api/v1/admin/revenue-share',headers=actors['admin']['headers']).json
    assert data['version']==0 and data['active']['driver_pct']=='85.00'
    for role in ('rider','driver'):
        assert client.get('/api/v1/admin/revenue-share',headers=actors[role]['headers']).status_code==403
        assert client.put('/api/v1/admin/revenue-share',headers=actors[role]['headers'],json={}).status_code==403


@pytest.mark.parametrize('values',[
    {'driver_pct':'81.00'}, {'driver_pct':'101.00','company_pct':'-1.00'},
    {'driver_pct':True}, {'driver_pct':'NaN'}, {'driver_pct':'80.001'},
    {'reason':''}, {'effective_from':'2020-01-01T00:00:00Z'},
    {'effective_from':'2035-01-01T00:00:00Z'}, {'effective_from':'2030-01-01T00:00:00'},
    {'effective_from':'9999-12-31T23:59:59-14:00'},
])
def test_invalid_settings_rejected(client,actors,values):
    assert save(client,actors,**values).status_code==400


def test_effective_split_snapshot_and_immutable_history(client,app,actors):
    ride=in_progress(client,actors)
    assert save(client,actors).status_code==200
    completed=post(client,actors,'driver',f"/rides/{ride['id']}/complete")
    assert completed.status_code==200
    allocation=completed.json['ride']['settlement']
    assert allocation['driver_pct']=='80.00' and allocation['share_version']==1
    expected=(Decimal(ride['quote']['total'])*Decimal('.80')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    assert Decimal(allocation['driver_amount'])==expected
    assert save(client,actors,version=1,driver_pct='90.00',company_pct='10.00').status_code==200
    retried=post(client,actors,'driver',f"/rides/{ride['id']}/complete")
    assert retried.json['ride']['settlement']==allocation
    history=client.get('/api/v1/admin/revenue-share',headers=actors['admin']['headers']).json['history']
    assert history[0]['previous_driver_pct']=='80.00' and history[0]['driver_pct']=='90.00'
    assert history[1]['driver_pct']=='80.00' and history[1]['updated_by']==actors['admin']['id']
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger))==1
        assert db.session.get(RevenueShareSetting,1).driver_pct==Decimal('80.00')


def test_future_effective_boundary_and_completion(client,app,actors):
    ride=in_progress(client,actors)
    future=utcnow()+timedelta(minutes=2)
    assert save(client,actors,effective_from=future.isoformat()+'Z').status_code==200
    data=client.get('/api/v1/admin/revenue-share',headers=actors['admin']['headers']).json
    assert data['active']['version']==0 and len(data['upcoming'])==1
    with app.app_context():
        assert revenue_service.active(future-timedelta(microseconds=1))['driver_pct']=='85.00'
        assert revenue_service.active(future)['driver_pct']=='80.00'
    with patch('app.ride_service.now',return_value=future):
        completed=post(client,actors,'driver',f"/rides/{ride['id']}/complete")
    assert completed.json['ride']['settlement']['share_version']==1


@pytest.mark.parametrize('driver,company',[('100.00','0.00'),('0.00','100.00'),('50.00','50.00')])
def test_extremes_and_cent_rounding(client,app,actors,driver,company):
    ride=in_progress(client,actors)
    assert save(client,actors,driver_pct=driver,company_pct=company).status_code==200
    with app.app_context():
        db.session.get(FareQuote,ride['quote']['id']).total=Decimal('.05')
        db.session.commit()
    allocation=post(client,actors,'driver',f"/rides/{ride['id']}/complete").json['ride']['settlement']
    assert Decimal(allocation['driver_amount'])+Decimal(allocation['company_amount'])==Decimal('.05')
    if driver=='50.00':
        assert allocation['driver_amount']=='0.03' and allocation['company_amount']=='0.02'


def test_same_timestamp_latest_revision_wins_and_old_revision_conflicts(client,app,actors):
    future=utcnow()+timedelta(days=1)
    assert save(client,actors,effective_from=future.isoformat()+'Z').status_code==200
    assert save(client,actors).status_code==409
    assert save(client,actors,version=1,driver_pct='75.00',company_pct='25.00',effective_from=future.isoformat()+'Z').status_code==200
    with app.app_context():
        assert revenue_service.active(future)['driver_pct']=='75.00'


def test_competing_admin_updates_preserve_one_revision(tmp_path):
    app=create_app({'TESTING':True,'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "revenue.db"}', 'JWT_SECRET':'test-revenue-jwt-key-12345678901234','USER_CODE_SECRET':'test-revenue-code-key-12345678901234'})
    with app.app_context():db.create_all()
    people=actors.__wrapped__(app)
    barrier=Barrier(2)
    def attempt():
        with app.test_client() as client:
            barrier.wait(timeout=5)
            return save(client,people).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        a,b=executor.submit(attempt),executor.submit(attempt)
        assert sorted([a.result(),b.result()])==[200,409]
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(RevenueShareSetting))==1

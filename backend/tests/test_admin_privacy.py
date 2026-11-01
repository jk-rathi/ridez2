import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from app import db
from app.models import FarePolicy, DriverLocation, AdminAudit, RevenueShareSetting
from app.fare_service import DEFAULT_POLICY
from app.location_service import utcnow
from test_auth import app,client
from test_rides import actors,prepare,book,post


def complete(client,actors):
    prepare(client,actors)
    ride=book(client,actors)
    assert 'settlement' not in ride
    for action in ('accept','depart','arrive','start','complete'):
        response=post(client,actors,'driver',f"/rides/{ride['id']}/{action}", **({'otp': client.get('/api/v1/workspace', headers=actors['rider']['headers']).json['trip_otp']} if action == 'start' else {}))
        assert response.status_code==200,response.json
    return ride,response.json['ride']


def assert_rider_private(data):
    forbidden={'settlement','driver_pct','company_pct','driver_amount','company_amount','share_version','eligible_fare','metrics','earnings','allocated_earnings'}
    if isinstance(data,dict):
        assert not (set(data)&forbidden)
        for value in data.values():assert_rider_private(value)
    elif isinstance(data,list):
        for value in data:assert_rider_private(value)


def test_rider_never_receives_split_but_fare_and_driver_admin_access_remain(client,actors):
    ride,completed=complete(client,actors)
    assert completed['settlement']['driver_pct']=='85.00'
    for response in [client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']),client.get('/api/v1/workspace',headers=actors['rider']['headers']),post(client,actors,'rider','/rides',quote_id=ride['quote']['id'])]:
        assert response.status_code in (200,201)
        assert_rider_private(response.json)
    rider=client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']).json['ride']
    assert rider['quote']['total']==ride['quote']['total']
    assert rider['driver']['name']=='driver'
    for role in ('driver','admin'):
        details=client.get('/api/v1/rides/'+ride['id'],headers=actors[role]['headers']).json['ride']
        assert details['settlement']['driver_amount']==completed['settlement']['driver_amount']
    assert client.get('/api/v1/rides/'+ride['id'],headers=actors['second']['headers']).status_code==404


def test_admin_metrics_use_live_state_and_private_allocation_totals(client,app,actors):
    ride,completed=complete(client,actors)
    prepare(client,actors,'second')
    data=client.get('/api/v1/workspace',headers=actors['admin']['headers']).json
    assert data['metrics']['completed_rides']==1 and data['metrics']['active_rides']==0
    assert data['metrics']['fresh_available_drivers']==2
    assert Decimal(data['metrics']['driver_allocations'])==Decimal(completed['settlement']['driver_amount'])
    with app.app_context():
        db.session.get(DriverLocation,actors['second']['id']).recorded_at=utcnow()-timedelta(seconds=91)
        db.session.commit()
    metrics=client.get('/api/v1/workspace',headers=actors['admin']['headers']).json['metrics']
    assert metrics['fresh_available_drivers']==1 and metrics['stale_available_drivers']==1


def audit_data(client,actors,**params):
    return client.get('/api/v1/admin/audit',headers=actors['admin']['headers'],query_string=params)


def test_audit_access_filters_details_and_search(client,app,actors):
    prepare(client,actors)
    policy=DEFAULT_POLICY|{'base':'55.00'}
    assert client.put('/api/v1/admin/fare-settings',headers=actors['admin']['headers'],json=dict(version=0,reason='Raise base fare',policy=policy)).status_code==200
    assert client.put('/api/v1/admin/revenue-share',headers=actors['admin']['headers'],json=dict(version=0,driver_pct='80',company_pct='20',reason='Reviewed 80/20 allocation')).status_code==200
    all_events=audit_data(client,actors).json
    assert all_events['total']==3
    assert {event['category'] for event in all_events['items']}=={'driver','fares','revenue'}
    assert audit_data(client,actors,category='fares').json['total']==1
    assert audit_data(client,actors,q='Raise base').json['total']==1
    assert audit_data(client,actors,q='admin').json['total']==3
    assert audit_data(client,actors,q='%').json['total']==0  # literal, not SQL wildcard
    for row in all_events['items']:
        response=client.get(f"/api/v1/admin/audit/{row['category']}/{row['id']}",headers=actors['admin']['headers'])
        assert response.status_code==200 and response.json['changes']
        if row['category']=='fares':
            assert response.json['changes'][0]==dict(field='Base fare',before='₹40.00',after='₹55.00')
        for role in ('rider','driver'):
            assert client.get(f"/api/v1/admin/audit/{row['category']}/{row['id']}",headers=actors[role]['headers']).status_code==403
    for role in ('rider','driver'):
        assert client.get('/api/v1/admin/audit',headers=actors[role]['headers']).status_code==403
    assert audit_data(client,actors,page='bad').status_code==400
    assert audit_data(client,actors,category='secrets').status_code==400
    assert client.get('/api/v1/admin/audit/fares/not-an-id',headers=actors['admin']['headers']).status_code==404


def test_audit_pagination_is_complete_and_stable(client,app,actors):
    with app.app_context():
        for i in range(25):
            db.session.add(AdminAudit(id=str(uuid4()),admin_id=actors['admin']['id'],driver_id=actors['driver']['id'],action='driver.approved',reason=f'Approval {i}',created_at=utcnow()+timedelta(seconds=i)))
        db.session.commit()
    first=audit_data(client,actors).json
    second=audit_data(client,actors,page=2).json
    assert first['total']==second['total']==25
    assert len(first['items'])==20 and len(second['items'])==5
    assert not ({row['id'] for row in first['items']}&{row['id'] for row in second['items']})

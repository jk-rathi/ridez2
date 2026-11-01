from unittest.mock import patch
from sqlalchemy import select, func
from app import db
from app.models import MockPayment, RevenueLedger
from test_auth import app, client
from test_rides import actors, prepare, book, post


def completed(client, actors):
    prepare(client, actors)
    ride = book(client, actors)
    for action in ['accept','depart','arrive','start','complete']:
        data = {'otp':client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']} if action=='start' else {}
        response = post(client,actors,'driver',f"/rides/{ride['id']}/{action}",**data)
        assert response.status_code == 200, response.json
    return response.json['ride']


def test_mock_flow_idempotent_success_and_financial_isolation(client, app, actors):
    ride=completed(client,actors)
    path=f"/rides/{ride['id']}/test-payment"
    created=post(client,actors,'rider',path).json
    assert created['payment']['amount']==ride['quote']['total']
    token=created['path'].split('/')[-1]
    public='/api/v1/test-payments/'+token
    assert set(client.get(public).json['payment'])=={'status','amount','currency','test_only'}
    for status in ['FAILED','PENDING','SUCCESS','FAILED','PENDING','SUCCESS']:
        response=client.post(public,json={'status':status})
        assert response.status_code==200
    assert response.json['payment']['status']=='SUCCESS'
    assert post(client,actors,'rider',path).json['payment']['status']=='SUCCESS'
    for role in ['rider','driver','admin']:
        rides=client.get('/api/v1/workspace',headers=actors[role]['headers']).json['rides']
        assert next(r for r in rides if r['id']==ride['id'])['test_payment']['status']=='SUCCESS'
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(MockPayment))==1
        assert db.session.scalar(select(func.count()).select_from(RevenueLedger))==1
        assert db.session.get(RevenueLedger,ride['id']).public()==ride['settlement']


def test_mock_access_expiry_and_disable(client, app, actors):
    prepare(client,actors)
    ride=book(client,actors)
    path=f"/rides/{ride['id']}/test-payment"
    assert post(client,actors,'other',path).status_code==404
    assert post(client,actors,'driver',path).status_code==403
    assert post(client,actors,'rider',path).status_code==409
    assert client.get('/api/v1/test-payments/tampered').status_code==410
    app.config['TEST_PAYMENTS_ENABLED']=False
    assert post(client,actors,'rider',path).status_code==404
    assert client.post('/api/v1/test-payments/anything',json={'status':'SUCCESS'}).status_code==404


def test_mock_expired_token_and_invalid_status(client, app, actors):
    ride=completed(client,actors)
    created=post(client,actors,'rider',f"/rides/{ride['id']}/test-payment").json
    endpoint='/api/v1/test-payments/'+created['path'].split('/')[-1]
    assert client.post(endpoint,json={'status':'PAID'}).status_code==400
    assert client.post(endpoint,json=[]).status_code==400
    with patch('time.time',return_value=__import__('time').time()+901):
        assert client.get(endpoint).status_code==410


def test_mock_result_notifies_rider_and_driver_once(client, app, actors):
    from app.models import OutboxEvent
    ride=completed(client,actors)
    token=post(client,actors,'rider',f"/rides/{ride['id']}/test-payment").json['path'].split('/')[-1]
    public='/api/v1/test-payments/'+token
    def events():
        with app.app_context():
            return sorted(str(user_id) for user_id in db.session.scalars(select(OutboxEvent.user_id)))
    before=events()
    assert client.post(public,json={'status':'SUCCESS'}).status_code==200
    added=list(events())
    for value in before:
        added.remove(value)
    assert sorted(added)==sorted([str(actors['rider']['id']),str(actors['driver']['id']),'None'])
    # Repeating the same result, or trying to downgrade success, changes nothing and sends nothing.
    after=events()
    assert client.post(public,json={'status':'SUCCESS'}).json['payment']['status']=='SUCCESS'
    assert client.post(public,json={'status':'FAILED'}).json['payment']['status']=='SUCCESS'
    assert events()==after

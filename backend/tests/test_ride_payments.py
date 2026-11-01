from decimal import Decimal
from test_auth import app, client
from test_rides import actors, post
from test_mock_payments import completed


def workspace(client, actors, role):
    return client.get('/api/v1/workspace', headers=actors[role]['headers']).json


def payment_of(client, actors, role, ride):
    return next(r for r in workspace(client, actors, role)['rides'] if r['id'] == ride['id'])['payment']


def test_completion_records_pending_payment_and_withholds_earnings(client, app, actors):
    ride = completed(client, actors)
    share = ride['settlement']['driver_amount']
    assert ride['payment'] == {'method': None, 'status': 'PENDING', 'amount': ride['quote']['total'], 'currency': 'INR', 'confirmed_at': None}
    driver = workspace(client, actors, 'driver')
    assert driver['allocated_earnings'] == share
    assert Decimal(driver['confirmed_earnings']) == 0 and driver['pending_earnings'] == share
    assert driver['earnings'][0]['payment']['status'] == 'PENDING'
    for role in ('rider', 'admin'):
        assert payment_of(client, actors, role, ride)['status'] == 'PENDING'


def test_cash_flow_confirmed_by_driver_counts_earnings_once(client, app, actors):
    ride = completed(client, actors)
    chosen = post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='CASH')
    assert chosen.status_code == 200 and chosen.json['payment']['method'] == 'CASH'
    assert payment_of(client, actors, 'driver', ride)['method'] == 'CASH'
    confirmed = post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash")
    assert confirmed.status_code == 200
    assert confirmed.json['payment']['status'] == 'CONFIRMED' and confirmed.json['payment']['confirmed_at']
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash").json['payment'] == confirmed.json['payment']
    driver = workspace(client, actors, 'driver')
    assert driver['confirmed_earnings'] == ride['settlement']['driver_amount'] and Decimal(driver['pending_earnings']) == 0
    # Paid in cash: the rider cannot switch to online, and the test QR is refused.
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='ONLINE').status_code == 409
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='CASH').status_code == 200
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/test-payment").status_code == 409


def test_driver_can_confirm_cash_without_rider_choice(client, app, actors):
    ride = completed(client, actors)
    response = post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash")
    assert response.status_code == 200 and response.json['payment']['method'] == 'CASH'


def test_online_success_confirms_and_blocks_cash(client, app, actors):
    ride = completed(client, actors)
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='ONLINE').json['payment']['method'] == 'ONLINE'
    token = post(client, actors, 'rider', f"/rides/{ride['id']}/test-payment").json['path'].split('/')[-1]
    assert client.post('/api/v1/test-payments/'+token, json={'status': 'FAILED'}).status_code == 200
    assert payment_of(client, actors, 'driver', ride)['status'] == 'PENDING'
    assert Decimal(workspace(client, actors, 'driver')['confirmed_earnings']) == 0
    assert client.post('/api/v1/test-payments/'+token, json={'status': 'SUCCESS'}).status_code == 200
    payment = payment_of(client, actors, 'rider', ride)
    assert payment['status'] == 'CONFIRMED' and payment['method'] == 'ONLINE'
    assert workspace(client, actors, 'driver')['confirmed_earnings'] == ride['settlement']['driver_amount']
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash").status_code == 409
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='CASH').status_code == 409


def test_cash_confirmed_first_blocks_later_online_success(client, app, actors):
    ride = completed(client, actors)
    token = post(client, actors, 'rider', f"/rides/{ride['id']}/test-payment").json['path'].split('/')[-1]
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash").status_code == 200
    assert client.post('/api/v1/test-payments/'+token, json={'status': 'SUCCESS'}).status_code == 409
    payment = payment_of(client, actors, 'admin', ride)
    assert payment['method'] == 'CASH' and payment['status'] == 'CONFIRMED'


def test_payment_permissions_and_states(client, app, actors):
    ride = completed(client, actors)
    path = f"/rides/{ride['id']}"
    assert post(client, actors, 'other', path+'/payment-method', method='CASH').status_code == 404
    assert post(client, actors, 'second', path+'/confirm-cash').status_code == 404
    assert post(client, actors, 'driver', path+'/payment-method', method='CASH').status_code == 403
    assert post(client, actors, 'rider', path+'/confirm-cash').status_code == 403
    assert post(client, actors, 'rider', path+'/payment-method', method='CARD').status_code == 400
    app.config['TEST_PAYMENTS_ENABLED'] = False
    assert post(client, actors, 'rider', path+'/payment-method', method='ONLINE').status_code == 409
    assert post(client, actors, 'rider', path+'/payment-method', method='CASH').status_code == 200


def test_payment_unavailable_before_completion(client, app, actors):
    from test_rides import prepare, book
    prepare(client, actors)
    ride = book(client, actors)
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='CASH').status_code == 409
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/accept").status_code == 200
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash").status_code == 409

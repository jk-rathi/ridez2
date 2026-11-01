import json
from app import db
from app.models import Ride
from app.services import trip_otp
from test_auth import app, client
from test_rides import actors, prepare, book, post


def to_waiting(client, actors, ride):
    for action in ('accept', 'depart', 'arrive'):
        assert post(client, actors, 'driver', f"/rides/{ride['id']}/{action}").status_code == 200
    return ride


def waiting(client, actors):
    prepare(client, actors)
    return to_waiting(client, actors, book(client, actors))


def rider_otp(client, actors, name='rider'):
    return client.get('/api/v1/workspace', headers=actors[name]['headers']).json['trip_otp']


def test_per_ride_private_code_and_required_start(client, app, actors):
    assert rider_otp(client, actors) is None
    ride = waiting(client, actors)
    otp = rider_otp(client, actors)
    assert len(otp) == 6 and otp.isascii() and otp.isdigit()
    # Re-fetching the persisted ride in a fresh context reproduces its code.
    with app.app_context():
        assert trip_otp(db.session.get(Ride, ride['id'])) == otp
    login = client.post('/api/v1/auth/login', json={'mobile': actors['rider']['mobile'], 'password': 'long-enough-password'})
    headers = {'Authorization': 'Bearer '+login.json['access_token']}
    assert client.get('/api/v1/workspace', headers=headers).json['trip_otp'] == otp
    path = f"/rides/{ride['id']}/start"
    for name in ('driver', 'admin', 'other'):
        data = client.get('/api/v1/workspace', headers=actors[name]['headers']).json
        if name == 'other':
            assert data['trip_otp'] is None
        else:
            assert 'trip_otp' not in json.dumps(data)
    for name in ('rider', 'second', 'admin'):
        assert post(client, actors, name, path, otp=otp).status_code in (403, 404)
    for data in ({}, {'otp': 'wrong'}, {'otp': int(otp)}, {'otp': f'{(int(otp)+1)%1000000:06d}'}):
        assert post(client, actors, 'driver', path, **data).status_code == 400
        assert client.get('/api/v1/rides/'+ride['id'], headers=actors['rider']['headers']).json['ride']['status'] == 'WAITING'
    response = post(client, actors, 'driver', path, otp=otp)
    assert response.status_code == 200
    assert response.json['ride']['status'] == 'IN_PROGRESS'
    assert 'trip_otp' not in json.dumps(response.json)
    assert rider_otp(client, actors) is None
    assert post(client, actors, 'driver', path, otp=otp).status_code == 200
    assert post(client, actors, 'driver', path).status_code == 400
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/complete").status_code == 200
    assert rider_otp(client, actors) is None


def test_previous_ride_code_cannot_start_next_ride(client, app, actors):
    first = waiting(client, actors)
    old = rider_otp(client, actors)
    assert post(client, actors, 'driver', f"/rides/{first['id']}/start", otp=old).status_code == 200
    assert post(client, actors, 'driver', f"/rides/{first['id']}/complete").status_code == 200
    second = to_waiting(client, actors, book(client, actors))
    assert second['id'] != first['id']
    new = rider_otp(client, actors)
    assert new and new != old
    path = f"/rides/{second['id']}/start"
    assert post(client, actors, 'driver', path, otp=old).status_code == 400
    assert post(client, actors, 'driver', path, otp=new).status_code == 200


def test_otp_attempt_limit(client, app, actors):
    from collections import deque
    from time import monotonic
    ride = waiting(client, actors)
    path = f"/rides/{ride['id']}/start"
    for _ in range(5):
        assert post(client, actors, 'driver', path, otp='bad').status_code == 400
    otp = rider_otp(client, actors)
    assert post(client, actors, 'driver', path, otp=otp).status_code == 429
    assert client.get('/api/v1/rides/'+ride['id'], headers=actors['rider']['headers']).json['ride']['status'] == 'WAITING'
    app.extensions['trip_otp_attempts'][actors['driver']['id']] = deque([monotonic()-61]*5)
    assert post(client, actors, 'driver', path, otp=otp).status_code == 200


def test_leading_zero_code(client, app, actors, monkeypatch):
    import app.ride_service as ride_service
    with app.app_context():
        for index in range(1000):
            ride_id = f'00000000-0000-4000-8000-{index:012d}'
            otp = trip_otp(Ride(id=ride_id))
            if otp.startswith('0'):
                break
    assert otp.startswith('0')
    monkeypatch.setattr(ride_service, 'uuid4', lambda: ride_id)
    ride = waiting(client, actors)
    assert ride['id'] == ride_id and rider_otp(client, actors) == otp
    assert post(client, actors, 'driver', f"/rides/{ride_id}/start", otp=otp).status_code == 200

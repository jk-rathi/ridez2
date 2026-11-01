from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select, func
import pytest
from app import create_app, db
from app.models import DriverLocation, Ride, Invitation, MatchRound, OutboxEvent, User
from app.location_service import utcnow, distance_m
from app.realtime import socketio, tick, dispatch
import jwt
from test_auth import app, client
from test_rides import actors, prepare, quote, book, post


def put_location(client, actors, **overrides):
    data=dict(latitude=19.076,longitude=72.8777,accuracy_m=10,recorded_at=utcnow().isoformat()+'Z') | overrides
    return client.put('/api/v1/driver/location',headers=actors['driver']['headers'],json=data)


@pytest.mark.parametrize('invalid',[
    {'latitude':91}, {'longitude':float('inf')}, {'latitude':True}, {'accuracy_m':-1}, {'accuracy_m':201},
    {'recorded_at':'2020-01-01T00:00:00Z'}, {'recorded_at':'no-time'}, {'recorded_at':utcnow().isoformat()},
])
def test_location_validation(client,actors,invalid):
    prepare(client,actors)
    assert put_location(client,actors,**invalid).status_code == 400


def test_location_identity_replay_and_movement(client, app, actors):
    prepare(client,actors)
    assert put_location(client,actors,driver_id=actors['second']['id']).status_code == 200
    with app.app_context():
        original=db.session.get(DriverLocation,actors['driver']['id'])
        recorded,updated=original.recorded_at,original.updated_at
        assert db.session.get(DriverLocation,actors['second']['id']) is None
    assert put_location(client,actors,recorded_at=recorded.isoformat()+'Z').status_code == 200
    with app.app_context():
        assert db.session.get(DriverLocation,actors['driver']['id']).updated_at == updated
    assert put_location(client,actors,latitude=20).status_code == 409
    assert put_location(client,actors,recorded_at=(recorded-timedelta(seconds=1)).isoformat()+'Z').status_code == 409
    assert post(client,actors,'driver','/driver/availability',available=False).status_code == 200
    assert put_location(client,actors).status_code == 409
    assert client.put('/api/v1/driver/location',headers=actors['rider']['headers'],json={}).status_code == 403


def test_stale_exclusion_at_matching_and_acceptance(client,app,actors):
    prepare(client,actors)
    ride=book(client,actors)
    with app.app_context():
        location=db.session.get(DriverLocation,actors['driver']['id'])
        location.recorded_at=utcnow()-timedelta(seconds=90)
        db.session.commit()
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code == 409
    snapshot=client.get('/api/v1/workspace',headers=actors['driver']['headers']).json
    assert snapshot['location']['fresh'] is False
    assert snapshot['invitations'] == []
    # A fresh report restores eligibility, but cannot revive an expired invitation.
    assert put_location(client,actors).status_code == 200
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code == 200


def test_radius_expansion_invites_only_new_fresh_candidates(client,app,actors):
    prepare(client,actors)
    prepare(client,actors,'second')
    with app.app_context():
        far=db.session.get(DriverLocation,actors['second']['id'])
        far.latitude += 0.006  # Approximately 667 m from pickup.
        db.session.commit()
    ride=book(client,actors)
    with app.app_context():
        record=db.session.get(Ride,ride['id'])
        first_deadline=record.expires_at
        assert db.session.get(Invitation,(ride['id'],actors['driver']['id'])) is not None
        assert db.session.get(Invitation,(ride['id'],actors['second']['id'])) is None
    # A scheduler tick, without any HTTP request, advances exactly one round.
    with patch('app.matching.utcnow',return_value=first_deadline):
        tick(app)
    with app.app_context():
        record=db.session.get(Ride,ride['id'])
        assert record.radius_m == 1000 and record.round_no == 2
        assert db.session.get(MatchRound,(ride['id'],1)).outcome == 'EXPIRED'
        assert db.session.get(Invitation,(ride['id'],actors['driver']['id'])).status == 'EXPIRED'
        assert db.session.get(Invitation,(ride['id'],actors['second']['id'])).round_no == 2
        assert db.session.scalar(select(func.count()).select_from(Invitation)) == 2
    with patch('app.matching.utcnow',return_value=first_deadline):
        tick(app)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(MatchRound)) == 2


def test_worker_recovers_all_overdue_rounds_and_stops_at_limit(client,app,actors):
    ride=book(client,actors)
    with app.app_context():
        deadline=db.session.get(Ride,ride['id']).expires_at
    app.config['MATCH_MAX_RADIUS_M']=1500
    # Equivalent to restarting a worker after downtime; no client polling.
    with patch('app.matching.utcnow',return_value=deadline+timedelta(seconds=61)):
        tick(app)
    with app.app_context():
        record=db.session.get(Ride,ride['id'])
        assert record.status == 'NO_DRIVER_FOUND' and record.round_no == 3
        assert db.session.scalar(select(func.count()).select_from(MatchRound)) == 3
    with patch('app.matching.utcnow',return_value=deadline+timedelta(seconds=61)):
        tick(app)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(MatchRound)) == 3


def test_realtime_auth_scoping_and_reconnect(client,app,actors):
    assert not socketio.test_client(app,auth={'token':'invalid'}).is_connected()
    rider=socketio.test_client(app,auth={'token':actors['rider']['headers']['Authorization'][7:]})
    other=socketio.test_client(app,auth={'token':actors['other']['headers']['Authorization'][7:]})
    driver=socketio.test_client(app,auth={'token':actors['driver']['headers']['Authorization'][7:]})
    prepare(client,actors)
    ride=book(client,actors)
    tick(app)
    assert any(event['name']=='workspace.changed' for event in rider.get_received())
    assert any(event['name']=='workspace.changed' for event in driver.get_received())
    assert other.get_received() == []
    rider.disconnect()
    post(client,actors,'driver',f"/rides/{ride['id']}/accept")
    tick(app)
    rider=socketio.test_client(app,auth={'token':actors['rider']['headers']['Authorization'][7:]})
    snapshot=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json
    assert snapshot['active_ride']['status']=='ASSIGNED'
    with app.app_context():
        db.session.get(User,actors['rider']['id']).status='disabled'
        db.session.commit()
    tick(app)
    assert not rider.is_connected()
    other.disconnect();driver.disconnect()


def test_expired_socket_token_rejected_and_existing_socket_disconnected(app,actors):
    past=utcnow()-timedelta(seconds=1)
    token=jwt.encode({'sub':str(actors['rider']['id']),'iat':(past-timedelta(seconds=10)).timestamp(),'exp':past.timestamp()},app.config['JWT_SECRET'],algorithm='HS256')
    assert not socketio.test_client(app,auth={'token':token}).is_connected()
    client=socketio.test_client(app,auth={'token':actors['rider']['headers']['Authorization'][7:]})
    assert client.is_connected()
    with app.app_context():
        for sid,(user_id,_,session_id) in app.extensions['ride_connections'].items():
            app.extensions['ride_connections'][sid]=(user_id,0,session_id)
        dispatch()
    assert not client.is_connected()


def test_outbox_retry_preserves_undelivered_event(client,app,actors):
    book(client,actors)
    with app.app_context():
        with patch.object(socketio,'emit',side_effect=RuntimeError('delivery failed')):
            with pytest.raises(RuntimeError):
                dispatch()
        db.session.rollback()
        assert db.session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.delivered_at.is_(None))) > 0
        dispatch()
        assert db.session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.delivered_at.is_(None))) == 0


def test_new_app_recovers_persisted_rounds(tmp_path):
    config={'ROUTE_PROVIDER':'simulator','SIMULATOR_ENABLED':True,'TESTING':True,'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "restart.db"}', 'JWT_SECRET':'restart-test-only-secret-key-123456', 'USER_CODE_SECRET':'restart-code-only-secret-key-123456', 'MATCH_MAX_RADIUS_M':1500}
    original=create_app(config)
    with original.app_context():
        db.create_all()
    people=actors.__wrapped__(original)
    with original.test_client() as client:
        ride=book(client,people)
    with original.app_context():
        deadline=db.session.get(Ride,ride['id']).expires_at
        db.session.remove()
    restarted=create_app(config)
    with patch('app.matching.utcnow',return_value=deadline+timedelta(seconds=61)):
        tick(restarted)
        tick(restarted)
    with restarted.app_context():
        assert db.session.get(Ride,ride['id']).status == 'NO_DRIVER_FOUND'
        assert db.session.scalar(select(func.count()).select_from(MatchRound)) == 3


def test_implausible_jump_rejected_only_while_tracking_is_fresh(client, app, actors):
    prepare(client, actors)
    # Mumbai to Delhi seconds later is impossible during continuous tracking.
    assert put_location(client, actors, latitude=28.6139, longitude=77.209).status_code == 409
    with app.app_context():
        location = db.session.get(DriverLocation, actors['driver']['id'])
        location.recorded_at = location.updated_at = utcnow()-timedelta(seconds=91)
        db.session.commit()
    # After a stale gap the old fix proves nothing, so the new position starts fresh tracking.
    response = put_location(client, actors, latitude=28.6139, longitude=77.209)
    assert response.status_code == 200 and response.json['location']['fresh']
    with app.app_context():
        assert round(db.session.get(DriverLocation, actors['driver']['id']).latitude, 4) == 28.6139

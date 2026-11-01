from datetime import timedelta
from unittest.mock import patch
import pytest
from app import db
from app.models import Ride, DriverLocation, FareQuote
from app.location_service import utcnow
from test_auth import app, client
from test_rides import actors, prepare, post
from test_google_fares import google_quote, fixture_response


def ride_fixture(client,app,actors,start=False):
    prepare(client,actors)
    with patch('app.route_provider.requests.post',return_value=fixture_response()):
        quote=google_quote(client,app,actors).json['quote']
    ride=post(client,actors,'rider','/rides',quote_id=quote['id']).json['ride']
    if start:
        for action in ('accept','depart','arrive'):
            assert post(client,actors,'driver',f"/rides/{ride['id']}/{action}").status_code==200
        otp=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']
        assert post(client,actors,'driver',f"/rides/{ride['id']}/start",otp=otp).status_code==200
    return ride


def load(client,actors,ride,role='rider'):
    return client.get(f"/api/v1/rides/{ride['id']}/map",headers=actors[role]['headers'])


def test_google_route_restores_for_both_roles_without_repricing(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    with patch('app.route_provider.requests.post',return_value=fixture_response(distanceMeters=2000)) as provider:
        rider=load(client,actors,ride)
        driver=load(client,actors,ride,'driver')
        again=load(client,actors,ride)
    assert rider.status_code==driver.status_code==again.status_code==200
    assert provider.call_count==1
    assert rider.json['map']['polyline'] and rider.json['map']==driver.json['map']
    assert rider.json['map']['phase']=='in_progress'
    assert rider.json['map']['origin_source']=='driver'
    assert rider.json['map']['driver_position']['lat']==19.076
    with app.app_context():
        quoted=db.session.get(FareQuote,ride['quote']['id'])
        assert str(quoted.total)==ride['quote']['total']
    assert 'settlement' not in rider.json['map'] and 'trip_otp' not in rider.json['map']


def test_route_phase_switch_and_current_driver_position(client,app,actors):
    ride=ride_fixture(client,app,actors)
    with patch('app.route_provider.requests.post',return_value=fixture_response()) as provider:
        assert load(client,actors,ride).json['map']['phase']=='overview'
        for action in ('accept','depart','arrive'):
            assert post(client,actors,'driver',f"/rides/{ride['id']}/{action}").status_code==200
        otp=client.get('/api/v1/workspace',headers=actors['rider']['headers']).json['trip_otp']
        post(client,actors,'driver',f"/rides/{ride['id']}/start",otp=otp)
        with app.app_context():
            db.session.get(DriverLocation,actors['driver']['id']).latitude=19.077
            db.session.commit()
        result=load(client,actors,ride)
        assert result.json['map']['origin_source']=='driver'
        assert provider.call_count==2
        assert provider.call_args.kwargs['json']['origin']['location']['latLng']['latitude']==19.077
        # Fresh marker updates do not cause another billable route request inside 60 seconds.
        with app.app_context():
            db.session.get(DriverLocation,actors['driver']['id']).latitude=19.0771
            db.session.commit()
        assert load(client,actors,ride).json['map']['driver_position']['lat']==19.0771
        assert provider.call_count==2


def test_stale_position_hidden_and_route_falls_back_to_pickup(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    with app.app_context():
        db.session.get(DriverLocation,actors['driver']['id']).recorded_at=utcnow()-timedelta(seconds=91)
        db.session.commit()
    with patch('app.route_provider.requests.post',return_value=fixture_response()) as provider:
        result=load(client,actors,ride).json['map']
    assert result['driver_position'] is None and result['origin_source']=='pickup'
    assert provider.call_args.kwargs['json']['origin']['location']['latLng']['latitude']==ride['quote']['pickup_lat']


def test_map_access_is_participant_only_and_active_only(client,app,actors):
    ride=ride_fixture(client,app,actors)
    with patch('app.route_provider.requests.post') as provider:
        assert load(client,actors,ride,'other').status_code==404
        assert load(client,actors,ride,'driver').status_code==404
        assert load(client,actors,ride,'admin').status_code==403
        assert client.get(f"/api/v1/rides/{ride['id']}/map").status_code==401
        assert provider.call_count==0
    assert post(client,actors,'rider',f"/rides/{ride['id']}/cancel").status_code==200
    assert load(client,actors,ride).status_code==409


def test_google_errors_do_not_fabricate_or_reprice_routes(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    with patch('app.route_provider.requests.post',return_value=fixture_response(403)) as provider:
        first=load(client,actors,ride)
        second=load(client,actors,ride,'driver')
    assert first.status_code==second.status_code==502
    assert provider.call_count==1
    assert 'polyline' not in first.json and 'test-server-key-not-real' not in str(first.json)
    details=client.get('/api/v1/rides/'+ride['id'],headers=actors['rider']['headers']).json['ride']
    assert details['quote']['total']==ride['quote']['total'] and details['status']=='IN_PROGRESS'


def test_no_driver_coordinates_after_completion_during_route_request(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    def complete(*args,**kwargs):
        db.session.get(Ride,ride['id']).status='COMPLETED'
        db.session.commit()
        return fixture_response()
    with patch('app.route_provider.requests.post',side_effect=complete):
        result=load(client,actors,ride)
    assert result.status_code==409 and 'driver_position' not in result.json


def test_cache_expiry_refreshes_google(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    with patch('app.route_provider.requests.post',return_value=fixture_response()) as provider:
        assert load(client,actors,ride).status_code==200
        for entry in app.extensions['trip_map_cache'].values():entry['expires']=0
        assert load(client,actors,ride).status_code==200
        assert provider.call_count==2


def test_exact_destination_does_not_request_zero_length_route(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    with app.app_context():
        location=db.session.get(DriverLocation,actors['driver']['id'])
        location.latitude=ride['quote']['destination_lat'];location.longitude=ride['quote']['destination_lng']
        db.session.commit()
    with patch('app.route_provider.requests.post') as provider:
        result=load(client,actors,ride)
    assert result.status_code==200 and result.json['map']['at_destination']
    assert result.json['map']['polyline'] is None and result.json['map']['distance_m']==0
    assert provider.call_count==0


def test_suspended_assigned_driver_can_still_use_trip_map(client,app,actors):
    ride=ride_fixture(client,app,actors,start=True)
    assert post(client,actors,'admin',f"/admin/drivers/{actors['driver']['id']}/suspend",version=1,reason='Review after current trip').status_code==200
    with patch('app.route_provider.requests.post',return_value=fixture_response()):
        assert load(client,actors,ride,'driver').status_code==200
        assert load(client,actors,ride).status_code==200


def test_cached_route_requests_are_coalesced_across_threads(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.trip_map_service import cached_route
    entered=Event();release=Event();calls=[]
    def compute():
        calls.append(1);entered.set();assert release.wait(timeout=5)
        return {'polyline':'fixture-road-route'}
    def fetch():
        with app.app_context():return cached_route(('shared-ride','in_progress'),compute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(fetch);assert entered.wait(timeout=5)
        second=pool.submit(fetch);release.set()
        assert first.result()==second.result()
    assert len(calls)==1


def move_driver(app,actors,lat,lng):
    with app.app_context():
        location=db.session.get(DriverLocation,actors['driver']['id'])
        location.latitude,location.longitude=lat,lng
        db.session.commit()


def test_approach_routes_driver_to_pickup_until_arrival(client,app,actors):
    ride=ride_fixture(client,app,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code==200
    move_driver(app,actors,19.07,72.87)
    with patch('app.route_provider.requests.post',return_value=fixture_response(distanceMeters=1200)) as provider:
        result=load(client,actors,ride).json['map']
        assert result['phase']=='approach' and result['origin_source']=='driver' and result['target']=='pickup'
        assert result['driver_position']['lat']==19.07 and not result['at_destination']
        body=provider.call_args.kwargs['json']
        assert body['origin']['location']['latLng']=={'latitude':19.07,'longitude':72.87}
        assert body['destination']['location']['latLng']=={'latitude':ride['quote']['pickup_lat'],'longitude':ride['quote']['pickup_lng']}
        # Heading to pickup stays in the same phase, so the cached route is reused.
        assert post(client,actors,'driver',f"/rides/{ride['id']}/depart").status_code==200
        assert load(client,actors,ride,'driver').json['map']['target']=='pickup'
        assert provider.call_count==1
        assert post(client,actors,'driver',f"/rides/{ride['id']}/arrive").status_code==200
        waiting=load(client,actors,ride).json['map']
        assert waiting['phase']=='overview' and waiting['target']=='destination' and waiting['origin_source']=='pickup'
        assert provider.call_args.kwargs['json']['destination']['location']['latLng']['latitude']==ride['quote']['destination_lat']
        assert provider.call_count==2


def test_approach_driver_at_pickup_skips_google(client,app,actors):
    ride=ride_fixture(client,app,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code==200
    with patch('app.route_provider.requests.post') as provider:
        result=load(client,actors,ride).json['map']
    assert result['target']=='pickup' and result['at_destination'] and result['polyline'] is None
    assert provider.call_count==0


def test_approach_with_stale_driver_shows_trip_route(client,app,actors):
    ride=ride_fixture(client,app,actors)
    assert post(client,actors,'driver',f"/rides/{ride['id']}/accept").status_code==200
    with app.app_context():
        db.session.get(DriverLocation,actors['driver']['id']).recorded_at=utcnow()-timedelta(seconds=91)
        db.session.commit()
    with patch('app.route_provider.requests.post',return_value=fixture_response()):
        result=load(client,actors,ride).json['map']
    assert result['phase']=='approach' and result['driver_position'] is None
    assert result['origin_source']=='pickup' and result['target']=='destination'

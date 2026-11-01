import copy
import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
import pytest
import requests
from sqlalchemy import select, func
from app import db
from app.models import FareQuote, FarePolicy, DriverLocation, Ride
from app.location_service import utcnow
from app import fare_service
from app.route_provider import compute
from app.services import ApiError
from test_auth import app, client
from test_rides import actors, post, book, prepare


def fixture_response(status=200,**route):
    response=Mock(status_code=status)
    response.json.return_value={'routes':[dict(distanceMeters=1537,duration='451.2s',staticDuration='300s',polyline={'encodedPolyline':'_p~iF~ps|U_ulLnnqC_mqNvxq`@'}) | route]}
    return response


def google_quote(client,app,actors):
    app.config.update(ROUTE_PROVIDER='google',GOOGLE_MAPS_SERVER_KEY='test-server-key-not-real')
    return post(client,actors,'rider','/fares/quotes',pickup='Pickup',destination='Destination',pickup_lat=19.076,pickup_lng=72.8777,destination_lat=19.08,destination_lng=72.88)


def save(client,actors,policy,version=0):
    return client.put('/api/v1/admin/fare-settings',headers=actors['admin']['headers'],json=dict(version=version,reason='Reviewed pricing policy',policy=policy))


def test_google_route_request_and_exact_fare_snapshot(client,app,actors):
    with patch('app.route_provider.requests.post',return_value=fixture_response()) as provider:
        response=google_quote(client,app,actors)
    assert response.status_code==201,response.json
    quote=response.json['quote']
    assert quote['provider']=='google' and quote['traffic_available'] is True
    assert quote['distance_m']==1537 and quote['duration_seconds']==452
    assert quote['distance_fare']=='18.44' and quote['time_fare']=='15.07'
    assert quote['total']=='73.51'
    assert quote['polyline']
    call=provider.call_args
    assert call.args[0]=='https://routes.googleapis.com/directions/v2:computeRoutes'
    assert call.kwargs['headers']['X-Goog-Api-Key']=='test-server-key-not-real'
    assert call.kwargs['json']['routingPreference']=='TRAFFIC_AWARE'
    assert call.kwargs['json']['origin']['location']['latLng']['latitude']==19.076
    assert call.kwargs['allow_redirects'] is False
    assert call.kwargs['timeout']==(3,10)
    assert 'test-server-key-not-real' not in json.dumps(response.json)
    with app.app_context():
        snapshot=db.session.get(FareQuote,quote['id'])
        assert 'polyline' not in snapshot.__table__.columns
        assert snapshot.total==Decimal('73.51')
    # Live mode can book with the simulator switched off.
    app.config['SIMULATOR_ENABLED']=False
    assert post(client,actors,'rider','/rides',quote_id=quote['id']).status_code==201


@pytest.mark.parametrize('status,expected',[(403,502),(429,503),(500,502),(302,502)])
def test_google_error_never_falls_back_or_leaks_response(client,app,actors,status,expected):
    with patch('app.route_provider.requests.post',return_value=fixture_response(status)):
        response=google_quote(client,app,actors)
    assert response.status_code==expected
    assert 'test-server-key-not-real' not in json.dumps(response.json)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(FareQuote))==0


@pytest.mark.parametrize('exception,expected',[(requests.Timeout,504),(requests.ConnectionError,502)])
def test_google_connection_failure(client,app,actors,exception,expected):
    with patch('app.route_provider.requests.post',side_effect=exception('private-provider-detail')):
        response=google_quote(client,app,actors)
    assert response.status_code==expected
    assert 'private-provider-detail' not in json.dumps(response.json)


def test_missing_route_key_and_no_route(client,app,actors):
    app.config.update(ROUTE_PROVIDER='google',GOOGLE_MAPS_SERVER_KEY='')
    with app.app_context():
        with pytest.raises(ApiError,match='not configured'):
            compute((19,72),(20,73),('A','B'))
    response=fixture_response()
    response.json.return_value={'routes':[]}
    with patch('app.route_provider.requests.post',return_value=response):
        assert google_quote(client,app,actors).status_code==422


@pytest.mark.parametrize('route',[{'distanceMeters':-1},{'distanceMeters':True},{'duration':'bad'},{'duration':'9999999999s'},{'staticDuration':'0s'},{'polyline':{'encodedPolyline':42}}])
def test_google_malformed_estimate(client,app,actors,route):
    with patch('app.route_provider.requests.post',return_value=fixture_response(**route)):
        assert google_quote(client,app,actors).status_code==502


def test_admin_policy_roles_validation_and_conflict(client,app,actors):
    policy=copy.deepcopy(fare_service.DEFAULT_POLICY)
    assert client.get('/api/v1/admin/fare-settings',headers=actors['rider']['headers']).status_code==403
    assert save(client,actors,policy).status_code==200
    assert save(client,actors,policy).status_code==409
    for patch_policy in [{'base':'-1'},{'max_multiplier':'6'},{'per_km':'nan'},{'timezone':'Nowhere/Invalid'},{'surge_enabled':'yes'}]:
        assert save(client,actors,policy|patch_policy,version=1).status_code==400
    settings=client.get('/api/v1/admin/fare-settings',headers=actors['admin']['headers']).json
    assert settings['version']==1 and settings['history'][0]['reason']=='Reviewed pricing policy'


def all_day_zone(**overrides):
    return dict(id='zone-one',name='Centre',latitude=19.076,longitude=72.8777,radius_m=1000,multiplier='3.00',days=list(range(7)),start='00:00',end='00:00',enabled=True) | overrides


def test_overlap_traffic_cap_minimum_and_quote_lock(client,app,actors):
    policy=copy.deepcopy(fare_service.DEFAULT_POLICY)
    policy.update(minimum='100.00',surge_enabled=True,traffic_enabled=True,traffic_multiplier='1.50',max_multiplier='2.00',zones=[all_day_zone(),all_day_zone(id='zone-two',name='Second',multiplier='1.75')])
    assert save(client,actors,policy).status_code==200
    with patch('app.route_provider.requests.post',return_value=fixture_response()):
        response=google_quote(client,app,actors)
    quoted=response.json['quote']
    assert quoted['minimum_adjustment']=='26.49'
    assert quoted['surge_multiplier']=='2.00' and quoted['total']=='200.00'
    assert 'capped' in quoted['surge_reason'] and 'Centre' in quoted['surge_reason']
    policy.update(base='80.00',surge_enabled=False)
    assert save(client,actors,policy,version=1).status_code==200
    booked=post(client,actors,'rider','/rides',quote_id=quoted['id'])
    assert booked.json['ride']['quote']['total']=='200.00'
    assert booked.json['ride']['quote']['fare_rule_version']==1
    with patch('app.route_provider.requests.post',return_value=fixture_response()):
        future=google_quote(client,app,actors).json['quote']
    assert future['total']=='113.51' and future['surge_multiplier']=='1.00'


def test_zone_timezone_overnight_and_boundary():
    zone=all_day_zone(start='22:00',end='02:00',days=[0])
    assert fare_service.scheduled(zone,datetime(2026,10,26,22,0)) # Monday inclusive start
    assert fare_service.scheduled(zone,datetime(2026,10,27,1,59)) # Tuesday belongs to Monday
    assert not fare_service.scheduled(zone,datetime(2026,10,27,2,0)) # Exclusive end
    assert not fare_service.scheduled(zone,datetime(2026,10,25,23,0))


def test_missing_traffic_and_demand_threshold(client,app,actors):
    policy=copy.deepcopy(fare_service.DEFAULT_POLICY)
    policy.update(surge_enabled=True,traffic_enabled=True,demand_enabled=True,demand_min_requests=5,demand_multiplier='1.50')
    assert save(client,actors,policy).status_code==200
    with app.app_context(),patch('app.fare_service.demand_signal',return_value=(5,Decimal('3'))):
        fare=fare_service.calculate(dict(distance_m=1000,duration_seconds=60,baseline_seconds=None),(19.076,72.8777))
        assert fare['total']==Decimal('81.00') and fare['surge_multiplier']==Decimal('1.50')
        assert 'demand' in fare['surge_reason']


def test_google_missing_traffic_is_explicit_and_does_not_trigger_surge(client,app,actors):
    policy=copy.deepcopy(fare_service.DEFAULT_POLICY)
    policy.update(surge_enabled=True,traffic_enabled=True,traffic_multiplier='2.00')
    assert save(client,actors,policy).status_code==200
    with patch('app.route_provider.requests.post',return_value=fixture_response(staticDuration=None)):
        quoted=google_quote(client,app,actors).json['quote']
    assert quoted['traffic_available'] is False
    assert quoted['total']=='73.51' and quoted['surge_multiplier']=='1.00'


def test_schedule_converts_utc_to_policy_timezone(client,app,actors):
    policy=copy.deepcopy(fare_service.DEFAULT_POLICY)
    policy.update(surge_enabled=True,zones=[all_day_zone(start='22:00',end='02:00',days=[0])])
    assert save(client,actors,policy).status_code==200
    route=dict(distance_m=1000,duration_seconds=60,baseline_seconds=None)
    with app.app_context():
        start=fare_service.calculate(route,(19.076,72.8777),at=datetime(2026,10,26,16,30))
        end=fare_service.calculate(route,(19.076,72.8777),at=datetime(2026,10,26,20,30))
    assert start['surge_multiplier']==Decimal('2.00') and end['surge_multiplier']==Decimal('1.00')


def test_demand_uses_live_requests_and_fresh_available_drivers(client,app,actors):
    prepare(client,actors)
    prepare(client,actors,'second')
    first=book(client,actors)
    book(client,actors,'other')
    with app.app_context():
        assert fare_service.demand_signal((19.076,72.8777),utcnow())==(2,Decimal('1'))
        db.session.get(DriverLocation,actors['second']['id']).recorded_at=utcnow()-timedelta(seconds=91)
        db.session.commit()
        assert fare_service.demand_signal((19.076,72.8777),utcnow())==(2,Decimal('2'))
        db.session.get(Ride,first['id']).expires_at=utcnow()-timedelta(seconds=1)
        db.session.commit()
        assert fare_service.demand_signal((19.076,72.8777),utcnow())==(1,Decimal('1'))


def test_quote_request_rate_limit(client,app,actors):
    for _ in range(10):
        assert post(client,actors,'rider','/fares/quotes',pickup='A',destination='B',pickup_lat=19,pickup_lng=72).status_code==201
    assert post(client,actors,'rider','/fares/quotes').status_code==429


def test_denial_reason_is_useful_without_exposing_metadata(client,app,actors):
    response=fixture_response(403)
    response.json.return_value={'error':{'message':'private key test-server-key-not-real and IP address','status':'PERMISSION_DENIED','details':[{'reason':'API_KEY_IP_ADDRESS_BLOCKED','metadata':{'private':'do-not-expose'}}]}}
    with patch('app.route_provider.requests.post',return_value=response):
        result=google_quote(client,app,actors)
    assert result.status_code==502 and 'API_KEY_IP_ADDRESS_BLOCKED' in result.json['error']
    assert 'test-server-key-not-real' not in result.json['error']
    assert 'do-not-expose' not in result.json['error']


def test_unknown_google_reason_is_not_echoed(client,app,actors):
    response=fixture_response(403)
    response.json.return_value={'error':{'details':[{'reason':'private-key-or-unknown-content'}]}}
    with patch('app.route_provider.requests.post',return_value=response):
        result=google_quote(client,app,actors)
    assert 'private-key-or-unknown-content' not in result.json['error']


def test_routing_diagnostic_uses_exact_provider_without_printing_key(app):
    app.config.update(ROUTE_PROVIDER='google',GOOGLE_MAPS_SERVER_KEY='private-test-cli-key')
    with patch('app.route_provider.requests.post',return_value=fixture_response()) as request:
        result=app.test_cli_runner().invoke(args=['check-routing','--probe'])
    assert result.exit_code==0 and 'Application route probe succeeded' in result.output
    assert 'private-test-cli-key' not in result.output
    assert request.call_args.kwargs['headers']['X-Goog-FieldMask'].endswith('routes.polyline.encodedPolyline')
    with patch('app.route_provider.requests.post') as request:
        result=app.test_cli_runner().invoke(args=['check-routing'])
    assert result.exit_code==0 and 'No Google request made' in result.output
    request.assert_not_called()

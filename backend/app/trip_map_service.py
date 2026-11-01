"""Participant-only trip maps; Google route geometry stays in a short-lived cache."""
from concurrent.futures import Future, TimeoutError
from threading import Lock
from time import monotonic
from flask import current_app
from . import db, ride_repository as repo, location_service, route_provider
from .models import FareQuote, DriverLocation
from .ride_service import accessible
from .services import ApiError

ACTIVE = {'SEARCHING', 'ASSIGNED', 'ARRIVING', 'WAITING', 'IN_PROGRESS'}
APPROACH = {'ASSIGNED', 'ARRIVING'}


def phase_for(ride):
    return 'in_progress' if ride.status == 'IN_PROGRESS' else 'approach' if ride.status in APPROACH else 'overview'


def source_for(phase, driver):
    return 'driver' if phase in ('in_progress', 'approach') and driver else 'pickup'


def cached_route(key, compute):
    cache = current_app.extensions.setdefault('trip_map_cache', {})
    lock = current_app.extensions.setdefault('trip_map_lock', Lock())
    with lock:
        at = monotonic()
        for old in list(cache):
            if cache[old]['future'].done() and cache[old]['expires'] <= at:
                del cache[old]
        entry = cache.get(key)
        owner = entry is None
        if owner:
            if len(cache) >= 256:
                completed = next((old for old in cache if cache[old]['future'].done()), None)
                if completed is None:
                    raise ApiError('Route updates are busy. Please try again shortly', 429)
                del cache[completed]
            entry = {'future': Future(), 'expires': at + 60}
            cache[key] = entry
    if owner:
        try:
            result = compute()
            from .location_service import utcnow
            value = {'route': result, 'generated_at': utcnow().isoformat()+'Z'}
        except ApiError as error:
            value = {'error': error.message, 'status': error.status}
        except Exception as error:
            with lock:
                cache.pop(key, None)
                entry['future'].set_exception(error)
            raise
        with lock:
            entry['expires'] = monotonic() + (10 if 'error' in value else 60)
            entry['future'].set_result(value)
    try:
        result = entry['future'].result(timeout=15)
    except TimeoutError:
        raise ApiError('The route update timed out. Please try again shortly', 504)
    if 'error' in result:
        raise ApiError(result['error'], result['status'])
    return result


def position(ride):
    location = repo.get(DriverLocation, ride.driver_id) if ride.driver_id else None
    if not location_service.is_fresh(location):
        return None
    return {'lat': location.latitude, 'lng': location.longitude,
            'recorded_at': location.recorded_at.isoformat()+'Z', 'accuracy_m': location.accuracy_m}


def trip_map(user, ride_id):
    if user.role not in ('rider', 'driver'):
        raise ApiError('Trip maps are available to the rider and assigned driver only', 403)
    ride = accessible(user, ride_id)
    if ride.status not in ACTIVE:
        raise ApiError('Live trip maps are only available for active rides', 409)
    quoted = repo.get(FareQuote, ride.quote_id)
    if quoted.provider != 'google':
        raise ApiError('Google road routes are unavailable for simulated rides', 409)
    if current_app.config['ROUTE_PROVIDER'] != 'google':
        raise ApiError('Google trip routing is currently unavailable', 503)
    pickup = {'lat': quoted.pickup_lat, 'lng': quoted.pickup_lng}
    destination = {'lat': quoted.destination_lat, 'lng': quoted.destination_lng}
    if any(value is None for point in (pickup, destination) for value in point.values()):
        raise ApiError('This ride does not have Google route coordinates', 409)
    phase = phase_for(ride)
    driver = position(ride)
    source = source_for(phase, driver)
    origin = (driver['lat'], driver['lng']) if source == 'driver' else (pickup['lat'], pickup['lng'])
    # While the driver heads to pickup, route them there; otherwise route towards the destination.
    towards = 'pickup' if phase == 'approach' and source == 'driver' else 'destination'
    end = pickup if towards == 'pickup' else destination
    target = (end['lat'], end['lng'])
    at_destination = origin == target
    def compute():
        if at_destination:
            return {'polyline': None, 'distance_m': 0, 'duration_seconds': 0, 'at_destination': True}
        result = route_provider.compute(origin, target, (quoted.pickup, quoted.destination))
        if not result.get('polyline'):
            raise ApiError('Google did not return a road route. Please retry shortly', 502)
        return {key: result[key] for key in ('polyline', 'distance_m', 'duration_seconds')} | {'at_destination': False}
    value = cached_route((ride.id, phase, source, towards, at_destination), compute)
    # A trip may complete while Google is responding. Do not expose live location afterwards.
    db.session.expire_all()
    ride = accessible(user, ride_id)
    if ride.status not in ACTIVE or phase_for(ride) != phase:
        raise ApiError('Ride state changed. Refresh the trip map', 409)
    driver = position(ride)
    if source_for(phase, driver) != source:
        raise ApiError('Driver location availability changed. Refresh the trip map', 409)
    return dict(provider='google', ride_id=ride.id, phase=phase, pickup=pickup, destination=destination,
                driver_position=driver, origin_source=source, target=towards, generated_at=value['generated_at'],
                refresh_after_seconds=10, **value['route'])

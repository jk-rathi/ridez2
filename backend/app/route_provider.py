import hashlib
import math
import re
from decimal import Decimal
import requests
from flask import current_app
from .services import ApiError


def denial_reason(response):
    """Expose only documented reason codes, never vendor messages or metadata."""
    allowed={'API_KEY_INVALID','API_KEY_EXPIRED','API_KEY_IP_ADDRESS_BLOCKED','API_KEY_HTTP_REFERRER_BLOCKED','API_KEY_SERVICE_BLOCKED','API_KEY_ANDROID_APP_BLOCKED','API_KEY_IOS_APP_BLOCKED','SERVICE_DISABLED','BILLING_DISABLED','CONSUMER_INVALID','PROJECT_INVALID','ACCESS_TOKEN_EXPIRED','PERMISSION_DENIED','UNAUTHENTICATED'}
    try:
        error=response.json().get('error',{})
        for detail in error.get('details',[]):
            reason=detail.get('reason')
            if isinstance(reason,str) and reason in allowed:
                return reason
        status=error.get('status')
        return status if isinstance(status,str) and status in allowed else None
    except (ValueError,TypeError,AttributeError):
        return None


def seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d{1,9})?s', value):
        raise ValueError('Invalid duration')
    result = math.ceil(Decimal(value[:-1]))
    if not 0 < result <= 604800:
        raise ValueError('Invalid duration')
    return result


def compute(pickup, destination, labels):
    provider = current_app.config['ROUTE_PROVIDER']
    if provider == 'simulator':
        if not current_app.config['SIMULATOR_ENABLED']:
            raise ApiError('Development ride simulator is disabled', 503)
        seed = int(hashlib.sha256('|'.join(label.casefold() for label in labels).encode()).hexdigest()[:8], 16)
        distance = (200 + seed % 1800) * 10
        return dict(provider='simulator', distance_m=distance, duration_seconds=max(5, int(Decimal(distance)/1000*3))*60, baseline_seconds=None, polyline=None)
    key = current_app.config['GOOGLE_MAPS_SERVER_KEY']
    if not key:
        raise ApiError('Google routing is not configured. Set GOOGLE_MAPS_SERVER_KEY in the backend environment', 503)
    if destination is None:
        raise ApiError('Select destination coordinates on the map or enter them manually')
    if pickup == destination:
        raise ApiError('Pickup and destination coordinates must be different')
    waypoint = lambda point: {'location': {'latLng': {'latitude': point[0], 'longitude': point[1]}}}
    try:
        response = requests.post(
            'https://routes.googleapis.com/directions/v2:computeRoutes',
            json={'origin':waypoint(pickup), 'destination':waypoint(destination), 'travelMode':'DRIVE', 'routingPreference':'TRAFFIC_AWARE', 'computeAlternativeRoutes':False, 'polylineQuality':'OVERVIEW'},
            headers={'X-Goog-Api-Key':key, 'X-Goog-FieldMask':'routes.distanceMeters,routes.duration,routes.staticDuration,routes.polyline.encodedPolyline'},
            timeout=(3, 10), allow_redirects=False,
        )
    except requests.Timeout:
        raise ApiError('The route service timed out. Try again shortly', 504)
    except requests.RequestException:
        raise ApiError('The route service is unavailable. No fare was generated', 502)
    if response.status_code == 429:
        raise ApiError('Google routing quota was reached. Try again later or review the project quota', 503)
    if response.status_code in (401,403):
        reason=denial_reason(response)
        suffix=f' Google reason: {reason}.' if reason else ''
        raise ApiError('Google routing access was denied. Check the server key, Routes API restrictions and billing.'+suffix, 502)
    if response.status_code != 200:
        raise ApiError('Google could not calculate this route. Check the locations and try again', 502)
    try:
        payload=response.json()
        routes=payload.get('routes')
        if not routes:
            raise ApiError('No driving route was found between these locations', 422)
        route=routes[0]
        distance=route.get('distanceMeters')
        if isinstance(distance,bool) or not isinstance(distance,int) or not 0 < distance <= 10000000:
            raise ValueError()
        duration=seconds(route.get('duration'))
        baseline=seconds(route['staticDuration']) if route.get('staticDuration') is not None else None
        polyline=route.get('polyline',{}).get('encodedPolyline')
        if polyline is not None and (not isinstance(polyline,str) or len(polyline)>200000):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, IndexError, KeyError):
        raise ApiError('The route provider returned an invalid estimate. Please retry', 502)
    return dict(provider='google',distance_m=distance,duration_seconds=duration,baseline_seconds=baseline,polyline=polyline)

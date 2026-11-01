import math
from datetime import datetime, timedelta, timezone
from flask import current_app
from . import ride_repository as repo
from .models import DriverLocation, DriverPresence, ActiveRide
from .services import ApiError


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def coordinate(value, name, bound):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > bound:
        raise ApiError(f'{name} must be a finite number between -{bound} and {bound}')
    return float(value)


def distance_m(lat1, lng1, lat2, lng2):
    lat1, lat2, delta = math.radians(lat1), math.radians(lat2), math.radians(lng2-lng1)
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(delta/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, value))))


def is_fresh(location, at=None):
    at = at or utcnow()
    cutoff = at - timedelta(seconds=current_app.config['LOCATION_STALE_SECONDS'])
    return bool(location and location.fresh and location.recorded_at > cutoff and location.updated_at > cutoff)


def public(location):
    return dict(fresh=is_fresh(location), recorded_at=location.recorded_at.isoformat()+'Z' if location else None, accuracy_m=location.accuracy_m if location else None)


def update(user, data, initializing=False):
    presence = repo.get(DriverPresence, user.id)
    active = repo.get(ActiveRide, user.id)
    if user.status != 'active' and not (user.status == 'suspended' and active and not initializing):
        raise ApiError('Driver approval is required', 403)
    if not initializing and not (presence and presence.available) and not active:
        raise ApiError('Location updates are only allowed while available or on a trip', 409)
    latitude = coordinate(data.get('latitude'), 'Latitude', 90)
    longitude = coordinate(data.get('longitude'), 'Longitude', 180)
    accuracy = coordinate(data.get('accuracy_m'), 'Accuracy', 200)
    if accuracy < 0:
        raise ApiError('Accuracy must be non-negative')
    try:
        raw = data.get('recorded_at')
        if not isinstance(raw, str) or len(raw) > 40:
            raise ValueError()
        captured = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if captured.tzinfo is None:
            raise ValueError()
        captured = captured.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise ApiError('Recorded time must be an ISO timestamp with timezone')
    received = utcnow()
    if captured > received + timedelta(seconds=15) or captured <= received - timedelta(seconds=current_app.config['LOCATION_STALE_SECONDS']):
        raise ApiError('Location time is stale or in the future')
    location = repo.get(DriverLocation, user.id)
    if location:
        if captured < location.recorded_at:
            raise ApiError('Location is older than the latest accepted update', 409)
        # Only continuous tracking can prove a jump impossible; after a stale gap the driver may
        # legitimately reappear anywhere, so a new starting fix is accepted.
        if is_fresh(location, received):
            movement = distance_m(location.latitude, location.longitude, latitude, longitude)
            seconds = max(0, (captured-location.recorded_at).total_seconds())
            if movement > seconds * (200000/3600) + location.accuracy_m + accuracy + 100:
                raise ApiError('Location movement is implausible', 409)
        if captured == location.recorded_at:
            return public(location)  # Replays must not refresh server receipt time.
    else:
        location = repo.add(DriverLocation(driver_id=user.id))
    location.latitude, location.longitude, location.accuracy_m = latitude, longitude, accuracy
    location.recorded_at, location.updated_at, location.fresh = captured, received, True
    repo.notify(user.id)
    return public(location)

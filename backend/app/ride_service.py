from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from flask import current_app
from sqlalchemy.exc import IntegrityError
from . import db
from . import ride_repository as repo
from .models import User, DriverPresence, FareQuote, Ride, ActiveRide, Invitation, RevenueLedger
from .services import ApiError, trip_otp, verify_trip_otp
from . import location_service, matching, route_provider, fare_service, revenue_service, payment_service
import math


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def simulator():
    if current_app.config['ROUTE_PROVIDER'] == 'simulator' and not current_app.config['SIMULATOR_ENABLED']:
        raise ApiError('Development ride simulator is disabled', 503)


def text(data, key, limit=160):
    value = data.get(key)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ApiError(f'{key.replace("_", " ").capitalize()} must contain 1–{limit} characters')
    return value.strip()


def quote(user, data):
    simulator()
    pickup, destination = text(data, 'pickup'), text(data, 'destination')
    latitude = location_service.coordinate(data.get('pickup_lat'), 'Pickup latitude', 90)
    longitude = location_service.coordinate(data.get('pickup_lng'), 'Pickup longitude', 180)
    if pickup.casefold() == destination.casefold():
        raise ApiError('Pickup and destination must be different')
    destination_point=None
    if data.get('destination_lat') is not None or data.get('destination_lng') is not None:
        destination_point=(location_service.coordinate(data.get('destination_lat'),'Destination latitude',90),location_service.coordinate(data.get('destination_lng'),'Destination longitude',180))
    expire()
    route=route_provider.compute((latitude,longitude),destination_point,(pickup,destination))
    fare=fare_service.calculate(route,(latitude,longitude))
    result=repo.add(FareQuote(id=str(uuid4()),rider_id=user.id,pickup=pickup,destination=destination,pickup_lat=latitude,pickup_lng=longitude,destination_lat=destination_point[0] if destination_point else None,destination_lng=destination_point[1] if destination_point else None,provider=route['provider'],distance_km=money(Decimal(route['distance_m'])/1000),distance_m=route['distance_m'],duration_min=math.ceil(route['duration_seconds']/60),duration_seconds=route['duration_seconds'],baseline_seconds=route['baseline_seconds'],expires_at=now()+timedelta(minutes=5),**fare))
    repo.commit()
    # Route geometry is returned for immediate display, not retained as raw provider data.
    return result.public() | {'polyline':route['polyline']}



def expire():
    matching.advance()
    db.session.expire_all()


def accessible(user, ride_id):
    ride = repo.get(Ride, ride_id)
    if not ride or (user.role != 'admin' and user.id not in (ride.rider_id, ride.driver_id)):
        raise ApiError('Ride not found', 404)
    return ride


def public(ride, user, invitation=False):
    quoted = repo.get(FareQuote, ride.quote_id)
    driver = repo.get(User, ride.driver_id) if ride.driver_id else None
    rider = repo.get(User, ride.rider_id)
    vehicle = {'registration':ride.vehicle_registration,'model':ride.vehicle_model,'color':ride.vehicle_color} if ride.vehicle_registration else None
    result = dict(id=ride.id, status=ride.status, round_no=ride.round_no, radius_m=ride.radius_m, quote=quoted.public(), requested_at=ride.requested_at.isoformat() + 'Z', expires_at=ride.expires_at.isoformat() + 'Z', driver={'name': driver.name, 'user_code': driver.user_code, 'vehicle':vehicle} if driver else None, rider={'name': rider.name}, completed_at=ride.completed_at.isoformat() + 'Z' if ride.completed_at else None)
    from .models import MockPayment
    from flask import current_app
    payment = db.session.get(MockPayment, ride.id)
    result['test_payment'] = payment.public() if payment else None
    from .models import RidePayment
    ride_payment = db.session.get(RidePayment, ride.id)
    result['payment'] = ride_payment.public() if ride_payment else None
    result['test_payments_enabled'] = current_app.config['TEST_PAYMENTS_ENABLED']
    result['cancellation'] = cancellation(ride, user) if ride.status == 'CANCELLED' else None
    if not invitation and user.role in ('driver','admin'):
        allocation = repo.get(RevenueLedger, ride.id)
        result['settlement'] = allocation.public() if allocation else None
    return result


def book(user, data):
    simulator()
    expire()
    quote_id = data.get('quote_id')
    if not isinstance(quote_id, str):
        raise ApiError('A quote_id is required')
    quoted = repo.get(FareQuote, quote_id)
    if not quoted or quoted.rider_id != user.id:
        raise ApiError('Quote not found', 404)
    existing = repo.ride_for_quote(quote_id)
    if existing:
        return public(existing, user)
    if quoted.expires_at <= now():
        raise ApiError('Quote expired. Request a new estimate', 409)
    if quoted.provider != current_app.config['ROUTE_PROVIDER']:
        raise ApiError('Route mode changed. Get a new quote before booking',409)
    if quoted.pickup_lat is None:
        raise ApiError('Get a new quote with pickup coordinates', 409)
    if repo.get(ActiveRide, user.id):
        raise ApiError('You already have an active ride', 409)
    ride = repo.add(Ride(id=str(uuid4()), rider_id=user.id, quote_id=quoted.id, status='SEARCHING', round_no=1, radius_m=500, requested_at=now(), expires_at=now() + timedelta(seconds=current_app.config['MATCH_ROUND_SECONDS'])))
    try:
        db.session.flush()
        repo.add(ActiveRide(user_id=user.id, ride_id=ride.id))
        matching.invite(ride, ride.requested_at)
        repo.notify_ride(ride)
        repo.commit()
    except IntegrityError:
        repo.rollback()
        existing = repo.ride_for_quote(quote_id)
        if existing:
            return public(existing, user)
        raise ApiError('You already have an active ride', 409)
    return public(ride, user)


def availability(user, data):
    expire()
    available = data.get('available')
    if not isinstance(available, bool):
        raise ApiError('Available must be true or false')
    if available:
        simulator()
    try:
        locked = repo.lock_active_driver(user.id) if available else repo.lock_driver(user.id)
        if not locked:
            repo.rollback()
            raise ApiError('Your driver status does not allow new requests', 403)
        db.session.refresh(user)
        from sqlalchemy import select, update
        active = db.session.scalar(select(ActiveRide).where(ActiveRide.user_id==user.id))
        if available:
            location_service.update(user, data, initializing=not bool(active))
        # Busy drivers stay unavailable until completion; persist their next-trip choice.
        online = available and not bool(active)
        repo.set_available(user.id, online, resume_available=available)
        if not available:
            db.session.execute(update(Invitation).where(Invitation.driver_id == user.id, Invitation.status == 'PENDING').values(status='OFFLINE'))
        repo.notify(user.id)
        repo.commit()
    except IntegrityError:
        repo.rollback()
        raise ApiError('Availability changed concurrently. Refresh and retry', 409)
    return dict(available=online, resume_available=available, active_trip=bool(active))


def accept(user, ride_id):
    simulator()
    expire()
    ride = repo.get(Ride, ride_id)
    invitation = repo.get(Invitation, (ride_id, user.id))
    presence = repo.get(DriverPresence, user.id)
    if not ride or not invitation:
        raise ApiError('Invitation not found', 404)
    if ride.driver_id == user.id and ride.status in ('ASSIGNED', 'ARRIVING', 'WAITING', 'IN_PROGRESS', 'COMPLETED'):
        return public(ride, user)
    if repo.get(ActiveRide, user.id):
        raise ApiError('You already have an active trip', 409)
    if user.status != 'active' or not presence or not presence.available:
        raise ApiError('You must be approved and available to accept', 403)
    from .models import DriverLocation
    if not location_service.is_fresh(repo.get(DriverLocation, user.id)):
        raise ApiError('Refresh your location before accepting', 409)
    if invitation.status != 'PENDING' or ride.status != 'SEARCHING' or ride.expires_at <= now():
        raise ApiError('This invitation is no longer available', 409)
    try:
        if not repo.lock_active_driver(user.id):
            repo.rollback()
            raise ApiError('Your driver status changed. New rides are blocked', 403)
        from .models import DriverVehicle
        if not repo.assign(ride.id, user.id, now(), repo.get(DriverVehicle, user.id)):
            repo.rollback()
            raise ApiError('Another driver has already accepted this ride', 409)
        repo.add(ActiveRide(user_id=user.id, ride_id=ride.id))
        repo.close_invitations(ride.id, 'CLOSED')
        invitation.status = 'ACCEPTED'
        repo.set_available(user.id, False)
        matching.close_round(ride, 'ASSIGNED')
        repo.notify_ride(ride)
        repo.commit()
    except IntegrityError:
        repo.rollback()
        raise ApiError('Driver or ride was assigned elsewhere. Refresh and retry', 409)
    db.session.expire_all()
    return public(repo.get(Ride, ride_id), user)


def reject(user, ride_id):
    expire()
    invitation = repo.get(Invitation, (ride_id, user.id))
    if not invitation:
        raise ApiError('Invitation not found', 404)
    if invitation.status == 'PENDING':
        invitation.status = 'REJECTED'
        repo.notify(user.id)
        repo.commit()
    return dict(status=invitation.status)


def cancellation(ride, user):
    actor = repo.get(User, ride.cancelled_by) if ride.cancelled_by else None
    return {'by': actor.role if actor else None, 'by_you': ride.cancelled_by == user.id,
            'reason': ride.cancellation_reason or 'Reason was not recorded',
            'cancelled_at': ride.cancelled_at.isoformat()+'Z' if ride.cancelled_at else None}


def move(user, ride_id, action, data=None):
    expire()
    ride = accessible(user, ride_id)
    if action == 'cancel':
        allowed = (user.role == 'rider' and ride.rider_id == user.id) or (user.role == 'driver' and ride.driver_id == user.id)
        if not allowed:
            raise ApiError('Only the rider or assigned driver can cancel this ride', 403)
        if ride.status == 'CANCELLED':
            return public(ride, user)
        if ride.status not in ('SEARCHING', 'ASSIGNED', 'ARRIVING', 'WAITING'):
            raise ApiError('Only rides that have not started can be cancelled', 409)
        if data is not None and not isinstance(data, dict):
            raise ApiError('A JSON object is required')
        payload = data or {}
        # Preserve old searching-cancellation clients; assigned-trip clients must supply a reason.
        if ride.status == 'SEARCHING' and 'reason' not in payload:
            reason = 'Rider cancelled the search'
        else:
            reason = text(payload, 'reason', 300)
        previous_status = ride.status
        if not repo.transition(ride.id, previous_status, 'CANCELLED', cancelled_at=now(), cancelled_by=user.id, cancellation_reason=reason):
            repo.rollback()
            raise ApiError('Ride changed. Refresh and review before cancelling', 409)
        repo.close_invitations(ride.id, 'CLOSED')
        if ride.driver_id:
            repo.set_available(ride.driver_id, False, resume_available=False)
        repo.release(ride.id)
        if previous_status == 'SEARCHING':
            matching.close_round(ride, 'CANCELLED')
    else:
        if user.role != 'driver' or ride.driver_id != user.id:
            raise ApiError('Only the assigned driver can progress this trip', 403)
        transitions = {'depart': ('ASSIGNED', 'ARRIVING'), 'arrive': ('ARRIVING', 'WAITING'), 'start': ('WAITING', 'IN_PROGRESS'), 'complete': ('IN_PROGRESS', 'COMPLETED')}
        if action not in transitions:
            raise ApiError('Unknown trip action', 404)
        old, new = transitions[action]
        if action == 'start' and ride.status in (old, new):
            verify_trip_otp(ride, user.id, (data or {}).get('otp'))
        if ride.status == new:
            return public(ride, user)
        if ride.status != old:
            raise ApiError(f'Cannot {action} a trip in {ride.status.lower()} state', 409)
        if action == 'complete':
            repo.lock_driver(user.id)
            db.session.refresh(user)
        completed_at=now() if action=='complete' else None
        if not repo.transition(ride.id, old, new, **({'completed_at': completed_at} if action == 'complete' else {})):
            repo.rollback()
            raise ApiError('Ride changed. Refresh and retry', 409)
        if action == 'complete':
            quoted = repo.get(FareQuote, ride.quote_id)
            revenue_service.allocate(ride,quoted,user.id,completed_at)
            payment_service.record_completion(ride, quoted, completed_at)
            repo.release(ride.id)
            from .models import DriverLocation
            presence = repo.get(DriverPresence, user.id)
            if presence:
                db.session.refresh(presence)
            eligible = (user.status == 'active' and bool(presence and presence.resume_available)
                and location_service.is_fresh(repo.get(DriverLocation, user.id), completed_at)
                and (current_app.config['ROUTE_PROVIDER'] == 'google' or current_app.config['SIMULATOR_ENABLED']))
            repo.set_available(user.id, eligible)
    repo.notify_ride(ride)
    repo.commit()
    db.session.expire_all()
    return public(repo.get(Ride, ride_id), user)


def snapshot(user):
    expire()
    rides = repo.all_rides(user)
    active = repo.get(ActiveRide, user.id)
    result = {'rides': [public(ride, user) for ride in rides], 'active_ride': public(repo.get(Ride, active.ride_id), user) if active else None, 'simulator': current_app.config['ROUTE_PROVIDER'] == 'simulator', 'route_provider':current_app.config['ROUTE_PROVIDER'], 'booking_enabled':current_app.config['ROUTE_PROVIDER'] == 'google' or current_app.config['SIMULATOR_ENABLED'], 'user': user.public()}
    if user.role in ('rider', 'driver'):
        latest = max(rides, key=lambda row: max(row.requested_at, row.cancelled_at or row.requested_at, row.completed_at or row.requested_at)) if rides else None
        result['recent_cancellation'] = ({'ride_id': latest.id, **cancellation(latest, user)}
            if not active and latest and latest.status == 'CANCELLED' and latest.cancelled_at
            and latest.cancelled_at >= now()-timedelta(minutes=10) else None)
    if user.role == 'rider':
        current = repo.get(Ride, active.ride_id) if active else None
        result['trip_otp'] = trip_otp(current) if current and current.status in ('SEARCHING', 'ASSIGNED', 'ARRIVING', 'WAITING') else None
    if user.role == 'driver':
        from .models import DriverLocation
        presence = repo.get(DriverPresence, user.id)
        result['location'] = location_service.public(repo.get(DriverLocation, user.id))
        entries = repo.ledger(user.id)
        from .models import RidePayment
        payments = {entry.ride_id: db.session.get(RidePayment, entry.ride_id) for entry in entries}
        paid = lambda entry: bool(payments[entry.ride_id] and payments[entry.ride_id].status == 'CONFIRMED')
        if user.status == 'suspended':
            from .models import AdminAudit
            from sqlalchemy import select
            review = db.session.scalar(select(AdminAudit).where(AdminAudit.driver_id==user.id, AdminAudit.action=='driver.suspended', AdminAudit.status_revision==user.status_revision))
            result['suspension'] = {'reason':review.reason,'created_at':review.created_at.isoformat()+'Z'} if review else None
        result.update(resume_available=bool(presence and presence.resume_available), available=bool(presence and presence.available), invitations=[public(ride, user, invitation=True) for ride in repo.invitations(user.id)] if user.status == 'active' and presence and presence.available and result['location']['fresh'] and not active else [], earnings=[entry.public() | {'payment': payments[entry.ride_id].public() if payments[entry.ride_id] else None} for entry in entries], allocated_earnings=str(money(sum((entry.driver_amount for entry in entries), Decimal(0)))),
            # Only payments the driver has received (cash) or that succeeded online count as earnings.
            confirmed_earnings=str(money(sum((entry.driver_amount for entry in entries if paid(entry)), Decimal(0)))),
            pending_earnings=str(money(sum((entry.driver_amount for entry in entries if not paid(entry)), Decimal(0)))))
    if user.role == 'admin':
        from .admin_service import metrics
        from .models import DriverLocation
        result['metrics']=metrics()
        result['drivers'] = [driver.public() | {'location': location_service.public(repo.get(DriverLocation, driver.id))} for driver in repo.drivers()]
    return result


def approve(user, driver_id, data):
    from .admin_service import change_driver_status
    return change_driver_status(user, driver_id, 'approve', data)

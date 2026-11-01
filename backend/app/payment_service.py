"""Per-ride payment: the rider picks cash or online; earnings count only once payment is confirmed."""
from flask import current_app
from sqlalchemy import update
from . import db, ride_repository as repo
from .models import Ride, RidePayment
from .location_service import utcnow
from .services import ApiError


def record_completion(ride, quoted, at):
    repo.add(RidePayment(ride_id=ride.id, status='PENDING', amount=quoted.total, updated_at=at))


def notify(ride):
    repo.notify(ride.rider_id, *([ride.driver_id] if ride.driver_id else []))


def completed_ride(ride_id):
    ride = db.session.get(Ride, ride_id)
    payment = db.session.get(RidePayment, ride_id)
    if not ride or ride.status != 'COMPLETED' or not payment:
        raise ApiError('Payment is only available for completed rides', 409)
    return ride, payment


def choose(user, ride_id, data):
    ride = db.session.get(Ride, ride_id)
    if not ride or ride.rider_id != user.id:
        raise ApiError('Ride not found', 404)
    ride, payment = completed_ride(ride_id)
    method = data.get('method')
    if method not in ('CASH', 'ONLINE'):
        raise ApiError('Choose CASH or ONLINE')
    if method == 'ONLINE' and not current_app.config['TEST_PAYMENTS_ENABLED']:
        raise ApiError('Online payment is not available. Please pay by cash', 409)
    if payment.status == 'CONFIRMED':
        if payment.method == method:
            return payment.public()
        raise ApiError('This ride is already paid', 409)
    if payment.method != method:
        changed = db.session.execute(update(RidePayment).where(RidePayment.ride_id == ride_id, RidePayment.status == 'PENDING')
                                     .values(method=method, updated_at=utcnow())).rowcount
        if not changed:
            db.session.rollback()
            raise ApiError('This ride is already paid', 409)
        notify(ride)
        db.session.commit()
    db.session.refresh(payment)
    return payment.public()


def confirm(ride_id, method, by=None):
    """Conditional write: the first confirmation wins, so a ride is never paid twice."""
    at = utcnow()
    return db.session.execute(update(RidePayment).where(RidePayment.ride_id == ride_id, RidePayment.status == 'PENDING')
                              .values(status='CONFIRMED', method=method, confirmed_at=at, confirmed_by=by, updated_at=at)).rowcount


def confirm_cash(user, ride_id):
    ride = db.session.get(Ride, ride_id)
    if not ride or ride.driver_id != user.id:
        raise ApiError('Ride not found', 404)
    ride, payment = completed_ride(ride_id)
    if payment.status == 'CONFIRMED':
        if payment.method == 'CASH':
            return payment.public()
        raise ApiError('The rider has already paid online', 409)
    if not confirm(ride_id, 'CASH', user.id):
        db.session.rollback()
        db.session.refresh(payment)
        if payment.method != 'CASH':
            raise ApiError('The rider has already paid online', 409)
        return payment.public()
    notify(ride)
    db.session.commit()
    db.session.refresh(payment)
    return payment.public()


def confirmed_by_other_method(ride_id):
    payment = db.session.get(RidePayment, ride_id)
    return bool(payment and payment.status == 'CONFIRMED' and payment.method != 'ONLINE')

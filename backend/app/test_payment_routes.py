"""Explicitly enabled mock QR capability, scoped to a completed ride for 15 minutes."""
from flask import current_app, g, jsonify
from itsdangerous import URLSafeTimedSerializer, BadData
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from . import db, ride_repository as repo, payment_service
from .routes import api, authenticated, body
from .models import Ride, FareQuote, MockPayment
from .services import ApiError


def enabled():
    if not current_app.config['TEST_PAYMENTS_ENABLED']:
        raise ApiError('Test payments are disabled', 404)


def signer():
    return URLSafeTimedSerializer(current_app.config['JWT_SECRET'], salt='mock-qr-payment-v1')


def payment_for(token):
    enabled()
    try:
        ride_id = signer().loads(token, max_age=900)
    except BadData:
        raise ApiError('Test QR expired or invalid. Generate a new QR from the rider workspace.', 410)
    payment = db.session.get(MockPayment, ride_id)
    if not payment:
        raise ApiError('Test payment not found', 404)
    return payment


@api.post('/rides/<ride_id>/test-payment')
@authenticated('rider')
def create_test_payment(ride_id):
    enabled()
    ride = db.session.get(Ride, ride_id)
    if not ride or ride.rider_id != g.user.id:
        raise ApiError('Ride not found', 404)
    if ride.status != 'COMPLETED':
        raise ApiError('Complete the trip before testing payment', 409)
    if payment_service.confirmed_by_other_method(ride_id):
        raise ApiError('This ride is already paid', 409)
    payment = db.session.get(MockPayment, ride_id)
    if not payment:
        quote = db.session.get(FareQuote, ride.quote_id)
        payment = MockPayment(ride_id=ride_id, amount=quote.total, status='PENDING')
        db.session.add(payment)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            payment = db.session.get(MockPayment, ride_id)
            if payment is None:
                raise
    return jsonify(payment=payment.public(), path='/test-payment/' + signer().dumps(ride_id), expires_in=900)


@api.get('/test-payments/<token>')
def view_test_payment(token):
    return jsonify(payment=payment_for(token).public())


@api.post('/test-payments/<token>')
def simulate_test_payment(token):
    payment = payment_for(token)
    status = body().get('status')
    if status not in ('PENDING', 'FAILED', 'SUCCESS'):
        raise ApiError('Choose PENDING, FAILED or SUCCESS')
    if payment_service.confirmed_by_other_method(payment.ride_id):
        raise ApiError('This ride is already paid in cash', 409)
    # Conditional database update prevents concurrent/repeated scans downgrading success.
    changed = db.session.execute(update(MockPayment).where(MockPayment.ride_id == payment.ride_id, MockPayment.status != 'SUCCESS', MockPayment.status != status).values(status=status)).rowcount
    if changed:
        if status == 'SUCCESS':
            payment_service.confirm(payment.ride_id, 'ONLINE')
        # Push the result so the rider's payment prompt updates immediately rather than on the next poll.
        ride = db.session.get(Ride, payment.ride_id)
        repo.notify(ride.rider_id, *([ride.driver_id] if ride.driver_id else []))
    db.session.commit()
    db.session.refresh(payment)
    return jsonify(payment=payment.public())

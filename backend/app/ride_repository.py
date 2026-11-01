from sqlalchemy import select, update, delete
from datetime import timedelta
from uuid import uuid4
from flask import current_app
from . import db
from .models import User, DriverPresence, FareQuote, Ride, ActiveRide, Invitation, RevenueLedger, DriverLocation, MatchRound, OutboxEvent


def get(model, key):
    return db.session.get(model, key)


def add(record):
    db.session.add(record)
    return record


def commit():
    db.session.commit()


def notify(*user_ids):
    from .location_service import utcnow
    for user_id in set(user_ids) | {None}:
        add(OutboxEvent(id=str(uuid4()), user_id=user_id, created_at=utcnow()))


def notify_ride(ride):
    ids = list(db.session.scalars(select(Invitation.driver_id).where(Invitation.ride_id == ride.id)))
    notify(ride.rider_id, *ids, *([ride.driver_id] if ride.driver_id else []))


def rollback():
    db.session.rollback()


def all_rides(user):
    query = select(Ride)
    if user.role == 'rider':
        query = query.where(Ride.rider_id == user.id)
    elif user.role == 'driver':
        query = query.where(Ride.driver_id == user.id)
    return db.session.scalars(query.order_by(Ride.requested_at.desc()).limit(100)).all()


def eligible_drivers(at):
    cutoff = at - timedelta(seconds=current_app.config['LOCATION_STALE_SECONDS'])
    return db.session.scalars(select(DriverPresence).join(User, User.id == DriverPresence.driver_id).join(DriverLocation, DriverLocation.driver_id == User.id).where(DriverPresence.available.is_(True), User.status == 'active', DriverLocation.fresh.is_(True), DriverLocation.recorded_at > cutoff, DriverLocation.updated_at > cutoff, ~DriverPresence.driver_id.in_(select(ActiveRide.user_id)))).all()


def transition(ride_id, old, new, **values):
    return db.session.execute(update(Ride).where(Ride.id == ride_id, Ride.status == old).values(status=new, **values).execution_options(synchronize_session=False)).rowcount == 1


def assign(ride_id, driver_id, now, vehicle=None):
    cutoff = now - timedelta(seconds=current_app.config['LOCATION_STALE_SECONDS'])
    valid_invitation = select(Invitation.ride_id).where(Invitation.driver_id == driver_id, Invitation.status == 'PENDING', Invitation.expires_at > now)
    eligible = select(DriverPresence.driver_id).join(User, User.id == DriverPresence.driver_id).join(DriverLocation, DriverLocation.driver_id == User.id).where(DriverPresence.driver_id == driver_id, DriverPresence.available.is_(True), User.status == 'active', DriverLocation.fresh.is_(True), DriverLocation.recorded_at > cutoff, DriverLocation.updated_at > cutoff).exists()
    return db.session.execute(update(Ride).where(Ride.id == ride_id, Ride.status == 'SEARCHING', Ride.expires_at > now, Ride.id.in_(valid_invitation), eligible).values(status='ASSIGNED', driver_id=driver_id, vehicle_registration=vehicle.registration if vehicle else None, vehicle_model=vehicle.model if vehicle else None, vehicle_color=vehicle.color if vehicle else None).execution_options(synchronize_session=False)).rowcount == 1


def release(ride_id):
    db.session.execute(delete(ActiveRide).where(ActiveRide.ride_id == ride_id))


def close_invitations(ride_id, status='EXPIRED'):
    db.session.execute(update(Invitation).where(Invitation.ride_id == ride_id, Invitation.status == 'PENDING').values(status=status))


def expire_round(ride, at):
    """Claim one exact persisted deadline; competing worker/request can only win once."""
    return db.session.execute(update(Ride).where(Ride.id == ride.id, Ride.status == 'SEARCHING', Ride.round_no == ride.round_no, Ride.expires_at == ride.expires_at, Ride.expires_at <= at).values(round_no=ride.round_no+1).execution_options(synchronize_session=False)).rowcount == 1


def round_for(ride):
    return get(MatchRound, (ride.id, ride.round_no))


def expired_searches(now):
    return db.session.scalars(select(Ride).where(Ride.status == 'SEARCHING', Ride.expires_at <= now)).all()


def invitations(driver_id):
    return db.session.scalars(select(Ride).join(Invitation, Invitation.ride_id == Ride.id).where(Invitation.driver_id == driver_id, Invitation.status == 'PENDING', Ride.status == 'SEARCHING').order_by(Ride.requested_at)).all()


def ledger(driver_id):
    return db.session.scalars(select(RevenueLedger).where(RevenueLedger.driver_id == driver_id)).all()


def drivers():
    return db.session.scalars(select(User).where(User.role == 'driver').order_by(User.id.desc()).limit(100)).all()


def ride_for_quote(quote_id):
    return db.session.scalar(select(Ride).where(Ride.quote_id == quote_id))


def set_available(driver_id, available, resume_available=None):
    presence = get(DriverPresence, driver_id)
    if not presence:
        presence = add(DriverPresence(driver_id=driver_id, available=available))
    else:
        presence.available = available
    if resume_available is not None:
        presence.resume_available = resume_available
    return presence


def lock_active_driver(driver_id, require_available=False):
    # Serialize availability/assignment with suspension using the same user row.
    query = update(User).where(User.id==driver_id, User.role=='driver', User.status=='active')
    if require_available:
        query = query.where(select(DriverPresence.driver_id).where(DriverPresence.driver_id==driver_id, DriverPresence.available.is_(True)).exists())
    return db.session.execute(query.values(status_revision=User.status_revision)).rowcount == 1


def lock_driver(driver_id):
    return db.session.execute(update(User).where(User.id==driver_id, User.role=='driver')
        .values(status_revision=User.status_revision)).rowcount == 1

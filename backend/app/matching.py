from datetime import timedelta
from sqlalchemy import select, update, or_
from . import db, ride_repository as repo
from .models import Ride, FareQuote, Invitation, MatchRound, DriverLocation
from .location_service import utcnow, distance_m
from flask import current_app


def invite(ride, started_at):
    quoted = repo.get(FareQuote, ride.quote_id)
    repo.add(MatchRound(ride_id=ride.id, round_no=ride.round_no, radius_m=ride.radius_m, started_at=started_at, expires_at=ride.expires_at, outcome='SEARCHING'))
    if ride.expires_at <= utcnow() or quoted.pickup_lat is None:
        return
    previous = set(db.session.scalars(select(Invitation.driver_id).where(Invitation.ride_id == ride.id)))
    for presence in repo.eligible_drivers(utcnow()):
        location = repo.get(DriverLocation, presence.driver_id)
        if presence.driver_id not in previous and distance_m(quoted.pickup_lat, quoted.pickup_lng, location.latitude, location.longitude) <= ride.radius_m:
            if not repo.lock_active_driver(presence.driver_id, require_available=True):
                continue
            repo.add(Invitation(ride_id=ride.id, driver_id=presence.driver_id, status='PENDING', round_no=ride.round_no, expires_at=ride.expires_at))


def advance():
    """Recover persisted deadlines, including after downtime. No sleeping in requests."""
    at = utcnow()
    # Bound catch-up by configured max radius. Only unexpired rounds send invitations.
    for _ in range(current_app.config['MATCH_MAX_RADIUS_M']//500+1):
        due = repo.expired_searches(at)
        if not due:
            break
        for ride in due:
            old_no, deadline = ride.round_no, ride.expires_at
            if not repo.expire_round(ride, at):
                repo.rollback()
                continue
            db.session.refresh(ride)
            old_round = repo.get(MatchRound, (ride.id, old_no))
            if old_round:
                old_round.outcome = 'EXPIRED'
            repo.close_invitations(ride.id)
            if ride.radius_m >= current_app.config['MATCH_MAX_RADIUS_M'] or repo.get(FareQuote, ride.quote_id).pickup_lat is None:
                # Keep final round number rather than the temporary claim increment.
                ride.round_no = old_no
                ride.status = 'NO_DRIVER_FOUND'
                repo.release(ride.id)
            else:
                ride.round_no = old_no+1
                ride.radius_m += 500
                ride.expires_at = deadline + timedelta(seconds=current_app.config['MATCH_ROUND_SECONDS'])
                invite(ride, deadline)
            repo.notify_ride(ride)
            repo.commit()
        db.session.expire_all()
    cutoff = at - timedelta(seconds=current_app.config['LOCATION_STALE_SECONDS'])
    stale = db.session.scalars(select(DriverLocation).where(DriverLocation.fresh.is_(True), or_(DriverLocation.recorded_at <= cutoff, DriverLocation.updated_at <= cutoff))).all()
    for location in stale:
        location.fresh = False
        repo.notify(location.driver_id)
    if stale:
        repo.commit()


def close_round(ride, outcome):
    round_record = repo.round_for(ride)
    if round_record:
        round_record.outcome = outcome

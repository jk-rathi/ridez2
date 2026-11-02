"""Two-way ratings: rider rates driver, driver rates rider, once each, after completion."""
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from . import db
from .models import Ride, RideRating
from .location_service import utcnow
from .services import ApiError

# Tags a rider may give a driver, and a driver may give a rider.
TAGS = {
    'rider': ('Great driving', 'Clean car', 'Friendly', 'On time', 'Smooth ride',
              'Unsafe driving', 'Late', 'Rude', 'Dirty car', 'Wrong route'),
    'driver': ('Polite', 'On time', 'Respectful', 'Late', 'Rude', 'Left a mess', 'Wrong pickup'),
}


def summary(user_id):
    average, count = db.session.execute(select(func.avg(RideRating.stars), func.count()).where(RideRating.ratee_id == user_id)).one()
    return {'average': f'{average:.1f}' if count else None, 'count': count}


def given(ride_id, role):
    return db.session.get(RideRating, (ride_id, role))


def for_admin(ride_id):
    return [rating.public() for rating in db.session.scalars(select(RideRating).where(RideRating.ride_id == ride_id).order_by(RideRating.rater_role.desc()))]


def submit(user, ride_id, data):
    ride = db.session.get(Ride, ride_id)
    role = user.role
    if not ride or (role == 'rider' and ride.rider_id != user.id) or (role == 'driver' and ride.driver_id != user.id):
        raise ApiError('Ride not found', 404)
    if ride.status != 'COMPLETED':
        raise ApiError('You can rate a trip once it is completed', 409)
    stars = data.get('stars')
    if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
        raise ApiError('Choose a rating from 1 to 5 stars')
    tags = data.get('tags', [])
    if not isinstance(tags, list) or len(tags) > 5 or any(tag not in TAGS[role] for tag in tags):
        raise ApiError('Choose up to five of the listed tags')
    comment = data.get('comment') or None
    if comment is not None:
        if not isinstance(comment, str) or len(comment.strip()) > 300:
            raise ApiError('Comment must be text of at most 300 characters')
        comment = comment.strip() or None
    rating = RideRating(ride_id=ride.id, rater_role=role, rater_id=user.id,
                        ratee_id=ride.driver_id if role == 'rider' else ride.rider_id,
                        stars=stars, tags='|'.join(dict.fromkeys(tags)) or None, comment=comment, created_at=utcnow())
    db.session.add(rating)
    try:
        db.session.commit()
    except IntegrityError:
        # Ratings are final: a retry with the same stars is accepted, a different one is refused.
        db.session.rollback()
        existing = given(ride.id, role)
        if existing.stars != stars:
            raise ApiError('You have already rated this trip', 409)
        rating = existing
    return rating.public()

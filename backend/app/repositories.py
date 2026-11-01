from sqlalchemy import select
from . import db
from .models import User


def by_mobile(mobile):
    return db.session.scalar(select(User).where(User.mobile == mobile))


def by_id(user_id):
    return db.session.get(User, user_id)


def code_exists(code):
    return db.session.scalar(select(User.id).where(User.user_code == code)) is not None


def save(user):
    db.session.add(user)
    db.session.commit()
    return user

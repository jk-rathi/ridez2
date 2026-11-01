from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import db, ride_repository as repo
from .models import RevenueShareSetting, RevenueLedger
from .location_service import utcnow
from .services import ApiError


def active(at=None):
    at=at or utcnow()
    record=db.session.scalar(select(RevenueShareSetting).where(RevenueShareSetting.effective_from<=at).order_by(RevenueShareSetting.effective_from.desc(),RevenueShareSetting.version.desc()).limit(1))
    return record.public() if record else dict(version=0,driver_pct='85.00',company_pct='15.00',effective_from=None)


def revision():
    return db.session.scalar(select(RevenueShareSetting.version).order_by(RevenueShareSetting.version.desc()).limit(1)) or 0


def settings():
    at=utcnow()
    rows=db.session.scalars(select(RevenueShareSetting).order_by(RevenueShareSetting.version.desc()).limit(100)).all()
    upcoming=db.session.scalars(select(RevenueShareSetting).where(RevenueShareSetting.effective_from>at).order_by(RevenueShareSetting.effective_from,RevenueShareSetting.version.desc()).limit(100)).all()
    return dict(version=revision(),active=active(at),upcoming=[row.public() for row in upcoming],history=[row.public() for row in rows],server_time=at.isoformat()+'Z')


def percentage(value):
    try:
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):
            raise ValueError()
        amount=Decimal(str(value))
        if not amount.is_finite() or not 0<=amount<=100 or amount!=amount.quantize(Decimal('.01')):
            raise ValueError()
        return amount.quantize(Decimal('.01'))
    except (ValueError,InvalidOperation):
        raise ApiError('Percentages must be between 0 and 100 with at most two decimals')


def save(user,data):
    current_revision=revision()
    if type(data.get('version')) is not int or data['version']!=current_revision:
        raise ApiError('Revenue settings changed. Reload before saving',409)
    driver,company=percentage(data.get('driver_pct')),percentage(data.get('company_pct'))
    if driver+company!=100:
        raise ApiError('Driver and company percentages must total exactly 100')
    reason=data.get('reason')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=300:
        raise ApiError('A change reason of 1–300 characters is required')
    at=utcnow()
    effective=data.get('effective_from')
    if effective is None:
        effective=at
    else:
        try:
            if not isinstance(effective,str) or len(effective)>40:
                raise ValueError()
            effective=datetime.fromisoformat(effective.replace('Z','+00:00'))
            if effective.tzinfo is None:
                raise ValueError()
            effective=effective.astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError,OverflowError):
            raise ApiError('Effective date must include a timezone, or use null for immediately')
        if effective<at or effective>at+timedelta(days=366):
            raise ApiError('Scheduled changes must be in the future and within one year')
    before=active(at)
    repo.add(RevenueShareSetting(version=current_revision+1,driver_pct=driver,company_pct=company,previous_driver_pct=Decimal(before['driver_pct']),previous_company_pct=Decimal(before['company_pct']),effective_from=effective,created_at=at,updated_by=user.id,reason=reason.strip()))
    try:
        repo.notify()
        repo.commit()
    except IntegrityError:
        repo.rollback()
        raise ApiError('Revenue settings changed concurrently. Reload before saving',409)
    return settings()


def allocate(ride,quoted,driver_id,completed_at):
    share=active(completed_at)
    driver_pct,company_pct=Decimal(share['driver_pct']),Decimal(share['company_pct'])
    amount=(quoted.total*driver_pct/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    return repo.add(RevenueLedger(ride_id=ride.id,driver_id=driver_id,eligible_fare=quoted.total,driver_pct=driver_pct,company_pct=company_pct,driver_amount=amount,company_amount=quoted.total-amount,share_version=share['version'],created_at=completed_at))

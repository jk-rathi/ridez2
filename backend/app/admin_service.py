import json
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from flask import current_app
from sqlalchemy import select, func, literal, cast, String, union_all, or_, update
from . import db, ride_repository as repo
from .models import DriverVehicle, User, Ride, DriverPresence, DriverLocation, ActiveRide, RevenueLedger, AdminAudit, FarePolicy, RevenueShareSetting
from .location_service import utcnow
from .fare_service import DEFAULT_POLICY
from .services import ApiError


def metrics():
    at=utcnow()
    cutoff=at-timedelta(seconds=current_app.config['LOCATION_STALE_SECONDS'])
    statuses=dict(db.session.execute(select(Ride.status,func.count()).group_by(Ride.status)).all())
    suspended=db.session.scalar(select(func.count()).select_from(User).where(User.role=='driver',User.status=='suspended'))
    pending=db.session.scalar(select(func.count()).select_from(User).where(User.role=='driver',User.status=='pending'))
    online=select(DriverPresence.driver_id).join(User,User.id==DriverPresence.driver_id).where(DriverPresence.available.is_(True),User.status=='active',~DriverPresence.driver_id.in_(select(ActiveRide.user_id)))
    available=db.session.scalar(select(func.count()).select_from(online.subquery()))
    fresh=db.session.scalar(select(func.count()).select_from(online.join(DriverLocation,DriverLocation.driver_id==DriverPresence.driver_id).where(DriverLocation.fresh.is_(True),DriverLocation.recorded_at>cutoff,DriverLocation.updated_at>cutoff).subquery()))
    driver,company=db.session.execute(select(func.sum(RevenueLedger.driver_amount),func.sum(RevenueLedger.company_amount))).one()
    return dict(active_rides=sum(count for status,count in statuses.items() if status in ('SEARCHING','ASSIGNED','ARRIVING','WAITING','IN_PROGRESS')),searching_rides=statuses.get('SEARCHING',0),completed_rides=statuses.get('COMPLETED',0),cancelled_rides=statuses.get('CANCELLED',0),fresh_available_drivers=fresh,stale_available_drivers=max(0,available-fresh),pending_driver_applications=pending,suspended_drivers=suspended,driver_allocations=str(driver or Decimal('0.00')),company_allocations=str(company or Decimal('0.00')),currency='INR',as_of=at.isoformat()+'Z')


def events():
    return union_all(
        select(cast(AdminAudit.id,String(36)).label('id'),literal('driver').label('category'),AdminAudit.action.label('action'),AdminAudit.admin_id.label('actor_id'),AdminAudit.created_at.label('created_at'),AdminAudit.reason.label('reason'),cast(AdminAudit.driver_id,String(36)).label('target')),
        select(cast(FarePolicy.version,String(36)),literal('fares'),literal('fare.settings.changed'),FarePolicy.updated_by,FarePolicy.created_at,FarePolicy.reason,cast(FarePolicy.version,String(36))),
        select(cast(RevenueShareSetting.version,String(36)),literal('revenue'),literal('revenue.share.changed'),RevenueShareSetting.updated_by,RevenueShareSetting.created_at,RevenueShareSetting.reason,cast(RevenueShareSetting.version,String(36))),
    ).subquery()


def audit(params):
    try:
        page=int(params.get('page','1'))
        if not 1<=page<=100000:
            raise ValueError()
    except (ValueError,TypeError):
        raise ApiError('Page must be a positive integer')
    category=params.get('category','')
    if category not in ('','driver','fares','revenue'):
        raise ApiError('Choose driver, fares or revenue category')
    query_text=params.get('q','').strip()
    if len(query_text)>100:
        raise ApiError('Search must contain at most 100 characters')
    source=events()
    query=select(source,User.name.label('actor_name')).join(User,User.id==source.c.actor_id)
    if category:
        query=query.where(source.c.category==category)
    if query_text:
        pattern='%'+query_text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.where(or_(source.c.reason.ilike(pattern,escape='\\'),User.name.ilike(pattern,escape='\\'),source.c.action.ilike(pattern,escape='\\')))
    total=db.session.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.session.execute(query.order_by(source.c.created_at.desc(),source.c.category,source.c.id.desc()).offset((page-1)*20).limit(20)).mappings().all()
    return dict(page=page,page_size=20,total=total,items=[dict(id=row['id'],category=row['category'],action=row['action'],actor_id=row['actor_id'],actor_name=row['actor_name'],created_at=row['created_at'].isoformat()+'Z',reason=row['reason'],target=row['target']) for row in rows])


def audit_detail(category,identifier):
    if category not in ('driver','fares','revenue'):
        raise ApiError('Audit entry not found',404)
    try:
        key=str(UUID(identifier)) if category=='driver' else int(identifier)
    except (ValueError,TypeError):
        raise ApiError('Audit entry not found',404)
    model={'driver':AdminAudit,'fares':FarePolicy,'revenue':RevenueShareSetting}[category]
    record=repo.get(model,key)
    if not record:
        raise ApiError('Audit entry not found',404)
    if category=='driver':
        driver=repo.get(User,record.driver_id)
        if record.action == 'driver.vehicle.updated' and record.details:
            details=json.loads(record.details)
            return dict(title='Driver vehicle details',subject=f'{driver.name} · {driver.user_code}' if driver else 'Driver account',changes=[{'field':label,'before':(details['before'] or {}).get(key) or 'Not provided','after':details['after'][key]} for key,label in [('registration','Car number'),('model','Car model'),('color','Colour')]])
        title,before,after = {'driver.approved':('Driver approval','pending','active'),'driver.suspended':('Driver suspension','active','suspended'),'driver.reinstated':('Driver reinstatement','suspended','active')}.get(record.action,('Driver status change','unknown','unknown'))
        return dict(title=title,subject=f'{driver.name} · {driver.user_code}' if driver else 'Driver account',changes=[dict(field='Account status',before=(record.before_status or before).capitalize(),after=(record.after_status or after).capitalize())])
    if category=='revenue':
        return dict(title='Revenue allocation change',effective_from=record.effective_from.isoformat()+'Z',changes=[dict(field='Driver share',before=f'{record.previous_driver_pct}%',after=f'{record.driver_pct}%'),dict(field='Company share',before=f'{record.previous_company_pct}%',after=f'{record.company_pct}%')])
    previous=repo.get(FarePolicy,record.version-1)
    before=json.loads(previous.settings) if previous else DEFAULT_POLICY
    after=json.loads(record.settings)
    labels={'base':'Base fare','per_km':'Fare per km','per_minute':'Fare per minute','minimum':'Minimum fare','timezone':'Schedule timezone','surge_enabled':'Surge enabled','max_multiplier':'Maximum surge','traffic_enabled':'Traffic surge enabled','traffic_threshold':'Traffic threshold','traffic_multiplier':'Traffic multiplier','demand_enabled':'Demand surge enabled','demand_threshold':'Demand threshold','demand_multiplier':'Demand multiplier','demand_min_requests':'Minimum demand requests','zones':'Surge zones'}
    def describe(key,value):
        if key=='zones':
            days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
            return '; '.join(f"{zone['name']} · {zone['multiplier']}× · {zone['radius_m']} m around {zone['latitude']}, {zone['longitude']} · {', '.join(days[day] for day in zone['days'])} · {zone['start']}–{zone['end']} · {'enabled' if zone['enabled'] else 'paused'}" for zone in value) or 'No zones'
        if isinstance(value,bool):
            return 'Enabled' if value else 'Disabled'
        return ('₹' if key in ('base','per_km','per_minute','minimum') else '')+str(value)
    return dict(title='Fare policy change',changes=[dict(field=labels.get(key,key),before=describe(key,before.get(key)),after=describe(key,value)) for key,value in after.items() if before.get(key)!=value])


DRIVER_TRANSITIONS = {
    'approve': ('pending', 'active', 'driver.approved'),
    'suspend': ('active', 'suspended', 'driver.suspended'),
    'reinstate': ('suspended', 'active', 'driver.reinstated'),
}


def change_driver_status(actor, driver_id, action, data):
    driver = repo.get(User, driver_id)
    if not driver or driver.role != 'driver':
        raise ApiError('Driver not found', 404)
    old, new, event = DRIVER_TRANSITIONS[action]
    reason = data.get('reason')
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
        raise ApiError('Reason must contain 1–300 characters')
    reason = reason.strip()
    version = data.get('version')
    legacy = action == 'approve' and version is None
    if not legacy and (type(version) is not int or version < 0):
        raise ApiError('A valid driver status version is required')
    if legacy:
        if driver.status == new:
            return driver.public()
        version = driver.status_revision
    if driver.status == new and driver.status_revision == version + 1:
        previous = db.session.scalar(select(AdminAudit).where(AdminAudit.driver_id==driver_id,
            AdminAudit.status_revision==version+1, AdminAudit.action==event,
            AdminAudit.admin_id==actor.id, AdminAudit.reason==reason))
        if previous:
            return driver.public()
    if driver.status_revision != version:
        raise ApiError('Driver status changed. Reload drivers and review again', 409)
    if driver.status != old:
        raise ApiError(f'Cannot {action} a {driver.status} driver', 409)
    changed = db.session.execute(update(User).where(User.id==driver_id, User.role=='driver',
        User.status==old, User.status_revision==version).values(status=new,status_revision=version+1)).rowcount
    if changed != 1:
        repo.rollback()
        raise ApiError('Driver status changed. Reload drivers and review again', 409)
    from .session_service import stop_requests
    stop_requests(driver_id)
    repo.add(AdminAudit(id=str(uuid4()), admin_id=actor.id, driver_id=driver_id, action=event,
        reason=reason, created_at=utcnow(), before_status=old, after_status=new, status_revision=version+1))
    repo.commit()
    db.session.expire_all()
    return repo.get(User, driver_id).public()


def driver_list(params):
    try:
        page=int(params.get('page','1'))
        if not 1 <= page <= 100000:
            raise ValueError()
    except (ValueError,TypeError):
        raise ApiError('Page must be a positive integer')
    status=params.get('status','')
    if status not in ('','pending','active','suspended','disabled'):
        raise ApiError('Choose a valid driver status')
    query_text=params.get('q','').strip()
    if len(query_text)>100:
        raise ApiError('Search must contain at most 100 characters')
    query=select(User).where(User.role=='driver')
    if status:
        query=query.where(User.status==status)
    if query_text:
        pattern='%'+query_text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.where(or_(User.name.ilike(pattern,escape='\\'),User.user_code.ilike(pattern,escape='\\'),User.mobile.ilike(pattern,escape='\\')))
    total=db.session.scalar(select(func.count()).select_from(query.subquery()))
    drivers=db.session.scalars(query.order_by(User.id.desc()).offset((page-1)*20).limit(20)).all()
    from .location_service import public as location_public
    items=[]
    for driver in drivers:
        claim=repo.get(ActiveRide,driver.id)
        ride=repo.get(Ride,claim.ride_id) if claim else None
        items.append(driver.public() | {'location':location_public(repo.get(DriverLocation,driver.id)),
            'active_ride':{'id':ride.id,'status':ride.status} if ride else None})
    return dict(page=page,page_size=20,total=total,items=items)


def save_driver_vehicle(actor, driver_id, data):
    import re
    driver=repo.get(User,driver_id)
    if not driver or driver.role!='driver':
        raise ApiError('Driver not found',404)
    version=data.get('version')
    if type(version) is not int or version<0:
        raise ApiError('A valid vehicle version is required')
    def text_value(key,limit):
        value=data.get(key)
        if not isinstance(value,str) or not 1<=len(value.strip())<=limit:
            raise ApiError(f'{key.capitalize()} must contain 1–{limit} characters')
        return ' '.join(value.split())
    registration=text_value('registration',20).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9 -]{3,19}',registration):
        raise ApiError('Car number must contain 4–20 letters, numbers, spaces or hyphens')
    model=text_value('model',80)
    color=text_value('color',40)
    reason=text_value('reason',300)
    # Serialize vehicle edits with assignment and driver reviews.
    db.session.execute(update(User).where(User.id==driver_id,User.role=='driver').values(status_revision=User.status_revision))
    db.session.refresh(driver)
    if driver.status=='disabled':
        raise ApiError('Disabled driver accounts require a separate review',409)
    if repo.get(ActiveRide,driver_id):
        raise ApiError('Vehicle details cannot change during an active trip',409)
    vehicle=repo.get(DriverVehicle,driver_id)
    before=vehicle.public() if vehicle else None
    current=vehicle.version if vehicle else 0
    if current!=version:
        raise ApiError('Vehicle details changed. Reload drivers and review again',409)
    if not vehicle:
        vehicle=repo.add(DriverVehicle(driver_id=driver_id))
    vehicle.registration,vehicle.model,vehicle.color=registration,model,color
    vehicle.version=version+1
    after=vehicle.public()
    repo.add(AdminAudit(id=str(uuid4()),admin_id=actor.id,driver_id=driver_id,action='driver.vehicle.updated',reason=reason,
        created_at=utcnow(),details=json.dumps({'before':before,'after':after})))
    repo.notify(driver_id)
    repo.commit()
    return driver.public()

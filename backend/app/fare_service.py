import copy
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import db, ride_repository as repo
from .models import FarePolicy, Ride, FareQuote, DriverLocation
from .location_service import coordinate, distance_m, utcnow
from .services import ApiError

DEFAULT_POLICY = dict(base='40.00',per_km='12.00',per_minute='2.00',minimum='40.00',timezone='Asia/Kolkata',surge_enabled=False,max_multiplier='2.00',traffic_enabled=False,traffic_threshold='1.25',traffic_multiplier='1.25',demand_enabled=False,demand_threshold='2.00',demand_multiplier='1.25',demand_min_requests=5,zones=[])


def money(value):
    return Decimal(value).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def current():
    row=db.session.scalar(select(FarePolicy).order_by(FarePolicy.version.desc()).limit(1))
    return (row.version,json.loads(row.settings)) if row else (0,copy.deepcopy(DEFAULT_POLICY))


def decimal_field(data,key,low='0',high='100000'):
    try:
        value=data[key]
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):
            raise ValueError()
        result=Decimal(str(value))
        if not result.is_finite() or not Decimal(low)<=result<=Decimal(high) or result != money(result):
            raise ValueError()
        return str(money(result))
    except (KeyError,InvalidOperation,ValueError):
        raise ApiError(f'{key} must be between {low} and {high}, with at most two decimals')


def validate(data):
    if not isinstance(data,dict):
        raise ApiError('Policy must be an object')
    policy={key:decimal_field(data,key) for key in ('base','per_km','per_minute','minimum')}
    for key in ('max_multiplier','traffic_multiplier','demand_multiplier'):
        policy[key]=decimal_field(data,key,'1','5')
    for key in ('traffic_threshold','demand_threshold'):
        policy[key]=decimal_field(data,key,'1','100')
    for key in ('surge_enabled','traffic_enabled','demand_enabled'):
        if not isinstance(data.get(key),bool):
            raise ApiError(f'{key} must be true or false')
        policy[key]=data[key]
    minimum=data.get('demand_min_requests')
    if isinstance(minimum,bool) or not isinstance(minimum,int) or not 1<=minimum<=1000:
        raise ApiError('Demand minimum requests must be an integer between 1 and 1000')
    policy['demand_min_requests']=minimum
    try:
        zone=data.get('timezone')
        if not isinstance(zone,str) or len(zone)>80:
            raise ValueError()
        ZoneInfo(zone)
    except (ValueError,ZoneInfoNotFoundError):
        raise ApiError('Enter a valid IANA timezone, for example Asia/Kolkata')
    policy['timezone']=zone
    zones=data.get('zones')
    if not isinstance(zones,list) or len(zones)>20:
        raise ApiError('Use at most 20 surge zones')
    policy['zones']=[]
    identifiers=set()
    for item in zones:
        if not isinstance(item,dict):
            raise ApiError('Every zone must be an object')
        name=item.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=60:
            raise ApiError('Zone name must contain 1–60 characters')
        identifier=item.get('id') or str(uuid4())
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,36}',identifier) or identifier in identifiers:
            raise ApiError('Zone IDs must be unique')
        identifiers.add(identifier)
        radius=item.get('radius_m')
        if isinstance(radius,bool) or not isinstance(radius,int) or not 100<=radius<=50000:
            raise ApiError('Zone radius must be an integer between 100 and 50000 metres')
        days=item.get('days')
        if not isinstance(days,list) or not days or any(type(day) is not int or day not in range(7) for day in days) or len(set(days))!=len(days):
            raise ApiError('Choose distinct weekdays for every zone (Monday=0)')
        for key in ('start','end'):
            if not isinstance(item.get(key),str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',item[key]):
                raise ApiError('Zone times must use HH:MM (24-hour format)')
        if not isinstance(item.get('enabled'),bool):
            raise ApiError('Zone enabled must be true or false')
        policy['zones'].append(dict(id=identifier,name=name.strip(),latitude=coordinate(item.get('latitude'),'Zone latitude',90),longitude=coordinate(item.get('longitude'),'Zone longitude',180),radius_m=radius,multiplier=decimal_field(item,'multiplier','1','5'),days=sorted(days),start=item['start'],end=item['end'],enabled=item['enabled']))
    return policy


def settings():
    version,policy=current()
    rows=db.session.scalars(select(FarePolicy).order_by(FarePolicy.version.desc()).limit(20)).all()
    return dict(version=version,policy=policy,history=[dict(version=row.version,reason=row.reason,updated_by=row.updated_by,created_at=row.created_at.isoformat()+'Z') for row in rows])


def save(user,data):
    version,_=current()
    if type(data.get('version')) is not int or data['version']!=version:
        raise ApiError('Fare settings changed. Reload before saving',409)
    reason=data.get('reason')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=300:
        raise ApiError('A change reason of 1–300 characters is required')
    policy=validate(data.get('policy'))
    repo.add(FarePolicy(version=version+1,settings=json.dumps(policy),updated_by=user.id,reason=reason.strip(),created_at=utcnow()))
    try:
        repo.notify()
        repo.commit()
    except IntegrityError:
        repo.rollback()
        raise ApiError('Fare settings changed concurrently. Reload before saving',409)
    return settings()


def scheduled(zone,local):
    time=local.strftime('%H:%M')
    start,end=zone['start'],zone['end']
    day=local.weekday()
    if start==end:
        return day in zone['days']
    if start<end:
        return day in zone['days'] and start<=time<end
    # For overnight windows the selected day is the day on which the window starts.
    return (day in zone['days'] and time>=start) or ((day-1)%7 in zone['days'] and time<end)


def demand_signal(pickup,at):
    requests=0
    rows=db.session.execute(select(Ride,FareQuote).join(FareQuote,Ride.quote_id==FareQuote.id).where(Ride.status=='SEARCHING',Ride.expires_at>at)).all()
    for ride,quoted in rows:
        if quoted.pickup_lat is not None and distance_m(*pickup,quoted.pickup_lat,quoted.pickup_lng)<=1000:
            requests+=1
    drivers=0
    for presence in repo.eligible_drivers(at):
        location=repo.get(DriverLocation,presence.driver_id)
        if distance_m(*pickup,location.latitude,location.longitude)<=1000:
            drivers+=1
    return requests,Decimal(requests)/max(1,drivers)


def calculate(route,pickup,at=None):
    version,policy=current()
    at=at or utcnow()
    base=Decimal(policy['base'])
    distance_fare=money(Decimal(route['distance_m'])/1000*Decimal(policy['per_km']))
    time_fare=money(Decimal(route['duration_seconds'])/60*Decimal(policy['per_minute']))
    components=base+distance_fare+time_fare
    subtotal=max(components,Decimal(policy['minimum']))
    multipliers=[(Decimal(1),'No surge')]
    traffic_ratio=None
    demand_ratio=None
    applied=[]
    if route['baseline_seconds']:
        traffic_ratio=Decimal(route['duration_seconds'])/route['baseline_seconds']
    if policy['surge_enabled']:
        local=at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(policy['timezone']))
        for zone in policy['zones']:
            if zone['enabled'] and scheduled(zone,local) and distance_m(*pickup,zone['latitude'],zone['longitude'])<=zone['radius_m']:
                multipliers.append((Decimal(zone['multiplier']),'Zone: '+zone['name']))
                applied.append(zone['id'])
        if policy['traffic_enabled'] and traffic_ratio is not None and traffic_ratio>=Decimal(policy['traffic_threshold']):
            multipliers.append((Decimal(policy['traffic_multiplier']),'Traffic threshold'))
        if policy['demand_enabled']:
            requests,demand_ratio=demand_signal(pickup,at)
            if requests>=policy['demand_min_requests'] and demand_ratio>=Decimal(policy['demand_threshold']):
                multipliers.append((Decimal(policy['demand_multiplier']),'High demand within 1 km'))
    highest=max(value for value,_ in multipliers)
    multiplier=min(highest,Decimal(policy['max_multiplier']))
    reason='; '.join(reason for value,reason in multipliers if value==highest and value>1) or 'No surge'
    if multiplier<highest:
        reason+=' (capped)'
    total=money(subtotal*multiplier)
    if total>Decimal('99999999.99'):
        raise ApiError('Fare exceeds the supported maximum. Review fare settings',422)
    snapshot={key:policy[key] for key in ('base','per_km','per_minute','minimum','max_multiplier','timezone')}
    snapshot.update(zone_ids=applied,traffic_ratio=str(traffic_ratio) if traffic_ratio is not None else None,demand_ratio=str(demand_ratio) if demand_ratio is not None else None)
    return dict(base=base,distance_fare=distance_fare,time_fare=time_fare,subtotal=subtotal,minimum_adjustment=subtotal-components,surge_multiplier=multiplier,surge_amount=total-subtotal,surge_reason=reason[:500],total=total,fare_rule_version=version,rate_snapshot=json.dumps(snapshot))

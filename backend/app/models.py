from datetime import datetime, timezone
from . import db


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    mobile = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    user_code = db.Column(db.String(40), unique=True, nullable=False)
    role = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='active')
    status_revision = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.CheckConstraint("role IN ('rider','driver','admin')", name='valid_user_role'), db.CheckConstraint("status IN ('active','pending','disabled','suspended') AND (status != 'suspended' OR role = 'driver')", name='valid_user_status'))

    def public(self):
        result = dict(id=self.id, name=self.name, mobile=self.mobile, user_code=self.user_code, role=self.role, status=self.status, status_revision=self.status_revision)
        if self.role == 'driver':
            vehicle = db.session.get(DriverVehicle, self.id)
            result['vehicle'] = vehicle.public() if vehicle else None
        return result


class DriverPresence(db.Model):
    __tablename__ = 'driver_presence'
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    available = db.Column(db.Boolean, nullable=False, default=False)
    resume_available = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


class FareQuote(db.Model):
    __tablename__ = 'fare_quotes'
    id = db.Column(db.String(36), primary_key=True)
    rider_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    pickup = db.Column(db.String(160), nullable=False)
    destination = db.Column(db.String(160), nullable=False)
    distance_km = db.Column(db.Numeric(10, 2), nullable=False)
    duration_min = db.Column(db.Integer, nullable=False)
    base = db.Column(db.Numeric(10, 2), nullable=False)
    distance_fare = db.Column(db.Numeric(10, 2), nullable=False)
    time_fare = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, index=True)
    pickup_lat = db.Column(db.Float)
    pickup_lng = db.Column(db.Float)
    destination_lat = db.Column(db.Float)
    destination_lng = db.Column(db.Float)
    provider = db.Column(db.String(16), nullable=False, default='simulator', server_default='simulator')
    distance_m = db.Column(db.Integer)
    duration_seconds = db.Column(db.Integer)
    baseline_seconds = db.Column(db.Integer)
    subtotal = db.Column(db.Numeric(10, 2))
    minimum_adjustment = db.Column(db.Numeric(10, 2))
    surge_multiplier = db.Column(db.Numeric(5, 2), nullable=False, default=1, server_default='1')
    surge_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0, server_default='0')
    surge_reason = db.Column(db.String(500), nullable=False, default='No surge', server_default='No surge')
    fare_rule_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    rate_snapshot = db.Column(db.Text)

    def public(self):
        return dict(id=self.id, pickup=self.pickup, destination=self.destination, pickup_lat=self.pickup_lat, pickup_lng=self.pickup_lng, destination_lat=self.destination_lat, destination_lng=self.destination_lng, distance_km=str(self.distance_km), distance_m=self.distance_m, duration_min=self.duration_min, duration_seconds=self.duration_seconds, traffic_available=self.baseline_seconds is not None, base=str(self.base), distance_fare=str(self.distance_fare), time_fare=str(self.time_fare), minimum_adjustment=str(self.minimum_adjustment or 0), subtotal=str(self.subtotal or self.total), surge_multiplier=str(self.surge_multiplier), surge_amount=str(self.surge_amount), surge_reason=self.surge_reason, fare_rule_version=self.fare_rule_version, total=str(self.total), currency='INR', provider=self.provider, expires_at=self.expires_at.isoformat() + 'Z')


class FarePolicy(db.Model):
    __tablename__ = 'fare_policies'
    version = db.Column(db.Integer, primary_key=True, autoincrement=False)
    settings = db.Column(db.Text, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)


class Ride(db.Model):
    __tablename__ = 'rides'
    id = db.Column(db.String(36), primary_key=True)
    rider_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    quote_id = db.Column(db.String(36), db.ForeignKey('fare_quotes.id'), unique=True, nullable=False)
    status = db.Column(db.String(24), nullable=False)
    requested_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    completed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    cancelled_by = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_rides_cancelled_by_users'))
    cancellation_reason = db.Column(db.String(300))
    vehicle_registration = db.Column(db.String(20))
    vehicle_model = db.Column(db.String(80))
    vehicle_color = db.Column(db.String(40))
    round_no = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    radius_m = db.Column(db.Integer, nullable=False, default=500, server_default='500')
    __table_args__ = (db.CheckConstraint("status IN ('SEARCHING','ASSIGNED','ARRIVING','WAITING','IN_PROGRESS','COMPLETED','CANCELLED','NO_DRIVER_FOUND')", name='valid_ride_state'),)


class ActiveRide(db.Model):
    # One row per participant: a portable uniqueness guard for concurrent assignments.
    __tablename__ = 'active_rides'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), nullable=False)


class Invitation(db.Model):
    __tablename__ = 'ride_invitations'
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    status = db.Column(db.String(16), nullable=False, default='PENDING')
    round_no = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    expires_at = db.Column(db.DateTime)


class DriverLocation(db.Model):
    __tablename__ = 'driver_locations'
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    accuracy_m = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, index=True)
    fresh = db.Column(db.Boolean, nullable=False, default=True)


class MatchRound(db.Model):
    __tablename__ = 'ride_match_rounds'
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), primary_key=True)
    round_no = db.Column(db.Integer, primary_key=True)
    radius_m = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    outcome = db.Column(db.String(24), nullable=False, default='SEARCHING')


class OutboxEvent(db.Model):
    __tablename__ = 'outbox_events'
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, nullable=False)
    delivered_at = db.Column(db.DateTime, index=True)


class RevenueLedger(db.Model):
    __tablename__ = 'revenue_ledger'
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    eligible_fare = db.Column(db.Numeric(10, 2), nullable=False)
    driver_pct = db.Column(db.Numeric(5, 2), nullable=False)
    company_pct = db.Column(db.Numeric(5, 2), nullable=False)
    driver_amount = db.Column(db.Numeric(10, 2), nullable=False)
    company_amount = db.Column(db.Numeric(10, 2), nullable=False)
    share_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime)

    def public(self):
        return {key: str(getattr(self, key)) for key in ('eligible_fare', 'driver_pct', 'company_pct', 'driver_amount', 'company_amount')} | {'currency': 'INR', 'status': 'ALLOCATED', 'ride_id': self.ride_id, 'share_version':self.share_version,'created_at':self.created_at.isoformat()+'Z' if self.created_at else None}


class RevenueShareSetting(db.Model):
    __tablename__ = 'revenue_share_settings'
    version = db.Column(db.Integer, primary_key=True, autoincrement=False)
    driver_pct = db.Column(db.Numeric(5, 2), nullable=False)
    company_pct = db.Column(db.Numeric(5, 2), nullable=False)
    previous_driver_pct = db.Column(db.Numeric(5, 2), nullable=False)
    previous_company_pct = db.Column(db.Numeric(5, 2), nullable=False)
    effective_from = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    __table_args__ = (db.CheckConstraint('driver_pct >= 0 AND driver_pct <= 100 AND company_pct >= 0 AND company_pct <= 100 AND driver_pct + company_pct = 100',name='valid_revenue_split'),)

    def public(self):
        return dict(version=self.version,driver_pct=str(self.driver_pct),company_pct=str(self.company_pct),previous_driver_pct=str(self.previous_driver_pct),previous_company_pct=str(self.previous_company_pct),effective_from=self.effective_from.isoformat()+'Z',created_at=self.created_at.isoformat()+'Z',updated_by=self.updated_by,reason=self.reason)


class AdminAudit(db.Model):
    __tablename__ = 'admin_audit'
    id = db.Column(db.String(36), primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)

    before_status = db.Column(db.String(16))
    after_status = db.Column(db.String(16))
    status_revision = db.Column(db.Integer)
    details = db.Column(db.Text)


class AuthSession(db.Model):
    __tablename__ = 'auth_sessions'
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)


class RefreshToken(db.Model):
    __tablename__ = 'refresh_tokens'
    token_hash = db.Column(db.String(64), primary_key=True)
    session_id = db.Column(db.String(36), db.ForeignKey('auth_sessions.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)


class DriverVehicle(db.Model):
    __tablename__ = 'driver_vehicles'
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    registration = db.Column(db.String(20), nullable=False)
    model = db.Column(db.String(80), nullable=False)
    color = db.Column(db.String(40), nullable=False)
    version = db.Column(db.Integer, nullable=False)

    def public(self):
        return {'registration':self.registration,'model':self.model,'color':self.color,'version':self.version}


class MockPayment(db.Model):
    """Testing only; never a payment receipt or money movement."""
    __tablename__ = 'mock_payments'
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), primary_key=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='PENDING')
    __table_args__ = (db.CheckConstraint("status IN ('PENDING','FAILED','SUCCESS')", name='valid_mock_payment_status'),)

    def public(self):
        return dict(status=self.status, amount=format(self.amount, '.2f'), currency='INR', test_only=True)


class RidePayment(db.Model):
    """How a completed ride is being paid; earnings count only once this is confirmed."""
    __tablename__ = 'ride_payments'
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), primary_key=True)
    method = db.Column(db.String(16))
    status = db.Column(db.String(16), nullable=False, default='PENDING')
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    confirmed_at = db.Column(db.DateTime)
    confirmed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    __table_args__ = (db.CheckConstraint("status IN ('PENDING','CONFIRMED')", name='valid_ride_payment_status'),
                      db.CheckConstraint("method IS NULL OR method IN ('CASH','ONLINE','UNRECORDED')", name='valid_ride_payment_method'),
                      db.CheckConstraint("status = 'PENDING' OR (method IS NOT NULL AND confirmed_at IS NOT NULL)", name='confirmed_ride_payment_complete'))

    def public(self):
        return dict(method=self.method, status=self.status, amount=format(self.amount, '.2f'), currency='INR',
                    confirmed_at=self.confirmed_at.isoformat()+'Z' if self.confirmed_at else None)


class RideRating(db.Model):
    """One final rating per participant per completed ride; comments are visible to admins only."""
    __tablename__ = 'ride_ratings'
    ride_id = db.Column(db.String(36), db.ForeignKey('rides.id'), primary_key=True)
    rater_role = db.Column(db.String(8), primary_key=True)
    rater_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ratee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    stars = db.Column(db.Integer, nullable=False)
    tags = db.Column(db.String(200))
    comment = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, nullable=False)
    __table_args__ = (db.CheckConstraint("rater_role IN ('rider','driver')", name='valid_rating_role'),
                      db.CheckConstraint('stars BETWEEN 1 AND 5', name='valid_rating_stars'))

    def public(self, include_comment=True):
        result = dict(rater_role=self.rater_role, stars=self.stars, tags=self.tags.split('|') if self.tags else [],
                      created_at=self.created_at.isoformat()+'Z')
        if include_comment:
            result['comment'] = self.comment
        return result

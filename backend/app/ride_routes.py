from flask import g, jsonify, request
from .routes import api, authenticated, body
from . import ride_service as service


@api.get('/workspace')
@authenticated()
def workspace():
    return jsonify(service.snapshot(g.user))


@api.post('/fares/quotes')
@authenticated('rider')
def quote():
    from time import monotonic
    from collections import deque
    from flask import current_app
    from .services import ApiError
    buckets=current_app.extensions.setdefault('quote_attempts',{})
    at=monotonic()
    for key in list(buckets):
        while buckets[key] and buckets[key][0]<=at-60:
            buckets[key].popleft()
        if not buckets[key]:
            del buckets[key]
    attempts=buckets.setdefault(g.user.id,deque())
    if len(attempts)>=10:
        raise ApiError('Too many fare requests. Try again in one minute',429)
    attempts.append(at)
    return jsonify(quote=service.quote(g.user, body())), 201


@api.post('/rides')
@authenticated('rider')
def book():
    return jsonify(ride=service.book(g.user, body())), 201


@api.get('/rides/<ride_id>')
@authenticated()
def details(ride_id):
    service.expire()
    return jsonify(ride=service.public(service.accessible(g.user, ride_id), g.user))


@api.post('/driver/availability')
@authenticated('driver')
def availability():
    return jsonify(service.availability(g.user, body()))


@api.put('/driver/location')
@authenticated('driver')
def location():
    from .location_service import update
    from . import ride_repository as repo
    result = update(g.user, body())
    repo.commit()
    return jsonify(location=result)


@api.post('/rides/<ride_id>/accept')
@authenticated('driver')
def accept(ride_id):
    return jsonify(ride=service.accept(g.user, ride_id))


@api.post('/rides/<ride_id>/reject')
@authenticated('driver')
def reject(ride_id):
    return jsonify(service.reject(g.user, ride_id))


@api.post('/rides/<ride_id>/payment-method')
@authenticated('rider')
def payment_method(ride_id):
    from . import payment_service
    return jsonify(payment=payment_service.choose(g.user, ride_id, body()))


@api.post('/rides/<ride_id>/confirm-cash')
@authenticated('driver')
def confirm_cash(ride_id):
    from . import payment_service
    return jsonify(payment=payment_service.confirm_cash(g.user, ride_id))


@api.post('/rides/<ride_id>/rating')
@authenticated()
def rate(ride_id):
    from . import rating_service
    if g.user.role not in ('rider', 'driver'):
        from .services import ApiError
        raise ApiError('Only the rider and driver of a trip can rate it', 403)
    return jsonify(rating=rating_service.submit(g.user, ride_id, body()))


@api.post('/rides/<ride_id>/<action>')
@authenticated()
def progress(ride_id, action):
    return jsonify(ride=service.move(g.user, ride_id, action, body() if action == 'start' else request.get_json(silent=True) if action == 'cancel' else None))


@api.post('/admin/drivers/<int:driver_id>/approve')
@authenticated('admin')
def approve(driver_id):
    return jsonify(user=service.approve(g.user, driver_id, body()))


@api.get('/admin/fare-settings')
@authenticated('admin')
def fare_settings():
    from .fare_service import settings
    return jsonify(settings())


@api.put('/admin/fare-settings')
@authenticated('admin')
def update_fare_settings():
    from .fare_service import save
    return jsonify(save(g.user,body()))


@api.get('/admin/revenue-share')
@authenticated('admin')
def revenue_share():
    from .revenue_service import settings
    return jsonify(settings())


@api.put('/admin/revenue-share')
@authenticated('admin')
def update_revenue_share():
    from .revenue_service import save
    return jsonify(save(g.user,body()))


@api.get('/admin/audit')
@authenticated('admin')
def admin_audit():
    from flask import request
    from .admin_service import audit
    return jsonify(audit(request.args))


@api.get('/admin/audit/<category>/<identifier>')
@authenticated('admin')
def admin_audit_detail(category,identifier):
    from .admin_service import audit_detail
    return jsonify(audit_detail(category,identifier))


@api.get('/admin/drivers')
@authenticated('admin')
def admin_drivers():
    from flask import request
    from .admin_service import driver_list
    return jsonify(driver_list(request.args))


@api.post('/admin/drivers/<int:driver_id>/suspend')
@authenticated('admin')
def suspend_driver(driver_id):
    from .admin_service import change_driver_status
    return jsonify(user=change_driver_status(g.user, driver_id, 'suspend', body()))


@api.post('/admin/drivers/<int:driver_id>/reinstate')
@authenticated('admin')
def reinstate_driver(driver_id):
    from .admin_service import change_driver_status
    return jsonify(user=change_driver_status(g.user, driver_id, 'reinstate', body()))


@api.get('/rides/<ride_id>/map')
@authenticated()
def trip_map(ride_id):
    from .trip_map_service import trip_map as load_map
    return jsonify(map=load_map(g.user, ride_id))


@api.put('/admin/drivers/<int:driver_id>/vehicle')
@authenticated('admin')
def update_driver_vehicle(driver_id):
    from .admin_service import save_driver_vehicle
    return jsonify(user=save_driver_vehicle(g.user, driver_id, body()))


@api.get('/admin/analytics')
@authenticated('admin')
def admin_analytics():
    from flask import request
    from .analytics_service import summary
    return jsonify(summary(request.args))


@api.get('/admin/analytics/export')
@authenticated('admin')
def admin_analytics_export():
    from flask import request
    from .analytics_service import export
    return jsonify(export(request.args))


@api.get('/ride-history/export')
@authenticated()
def ride_history_export():
    from flask import request
    from .analytics_service import history_export
    return jsonify(history_export(g.user, request.args))

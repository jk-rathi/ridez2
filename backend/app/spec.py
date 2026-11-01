ERROR = {'description': 'Validation, authentication or permission error', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {'error': {'type': 'string'}}}}}}
USER = {'type': 'object', 'properties': {key: {'type': 'string'} for key in ['name', 'mobile', 'user_code', 'role', 'status']}}


def operation(summary, fields=None, protected=False, status='200'):
    result = {'summary': summary, 'responses': {status: {'description': 'Success'}, '400': ERROR, '401': ERROR, '403': ERROR, '409': ERROR, '429': ERROR}}
    if fields:
        result['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'type': 'object', 'required': list(fields), 'properties': {key: {'type': 'string', **({'enum': ['rider', 'driver']} if key == 'role' else {}), **({'format': 'password'} if key == 'password' else {})} for key in fields}}}}}
    if protected:
        result['security'] = [{'bearerAuth': []}]
    return result


SPEC = {
    'openapi': '3.0.3',
    'info': {'title': 'ridez foundation API', 'version': '0.1.0', 'description': 'Mobile/password authentication and role-protected foundation. Access tokens expire after 15 minutes; a rotating HttpOnly cookie restores sessions for up to 30 days.'},
    'servers': [{'url': '/api/v1'}],
    'components': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}}, 'schemas': {'User': USER}},
    'paths': {
        '/health': {'get': operation('Runtime health and development storage mode')},
        '/auth/register': {'post': operation('Register rider or pending driver', ['name', 'mobile', 'password', 'role'], status='201')},
        '/auth/login': {'post': operation('Sign in with mobile and password', ['mobile', 'password'])},
        '/me': {'get': operation('Read your profile', protected=True)},
        '/driver/overview': {'get': operation('Driver-only workspace overview', protected=True)},
        '/admin/overview': {'get': operation('Admin-only foundation overview', protected=True)},
    },
}

SPEC['info']['version'] = '0.7.0'
SPEC['info']['title'] = 'ridez routes, fares and matching API'
SPEC['info']['description'] += ' Sample route fares; real GPS matching starts at 500 m and expands by 500 m every 30 seconds. Driver locations expire after 90 seconds. No live geocoding or payments. Socket.IO authenticates with auth.token and sends scoped workspace.changed invalidations; fetch /workspace on reconnect.'
SPEC['paths'].update({
    '/workspace': {'get': operation('Read your rides, active trip, invitations, earnings or admin driver queue', protected=True)},
    '/fares/quotes': {'post': operation('Create a five-minute simulated quote with pickup coordinates', ['pickup', 'destination', 'pickup_lat', 'pickup_lng'], protected=True, status='201')},
    '/rides': {'post': operation('Book a quote; quote ID is the idempotency key', ['quote_id'], protected=True, status='201')},
    '/driver/availability': {'post': operation('Change approved driver simulator availability', protected=True)},
})
SPEC['paths']['/driver/availability']['post']['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'type': 'object', 'required': ['available'], 'properties': {'available': {'type': 'boolean'}}}}}}
location_schema = {'type': 'object', 'required': ['latitude','longitude','accuracy_m','recorded_at'], 'properties': {'latitude': {'type':'number','minimum':-90,'maximum':90}, 'longitude': {'type':'number','minimum':-180,'maximum':180}, 'accuracy_m': {'type':'number','minimum':0,'maximum':200}, 'recorded_at': {'type':'string','format':'date-time'}}}
SPEC['paths']['/driver/location'] = {'put': operation('Update your own current location while available or on a trip', protected=True)}
SPEC['paths']['/driver/location']['put']['requestBody'] = {'required':True,'content':{'application/json':{'schema':location_schema}}}
availability_schema = SPEC['paths']['/driver/availability']['post']['requestBody']['content']['application/json']['schema']
availability_schema['properties'].update(location_schema['properties'])
availability_schema['description'] = 'All location fields are required when available=true. Only available=false is required to go offline.'
quote_properties = SPEC['paths']['/fares/quotes']['post']['requestBody']['content']['application/json']['schema']['properties']
quote_properties['pickup_lat'] = location_schema['properties']['latitude']
quote_properties['pickup_lng'] = location_schema['properties']['longitude']
quote_properties['destination_lat'] = location_schema['properties']['latitude']
quote_properties['destination_lng'] = location_schema['properties']['longitude']
SPEC['paths']['/fares/quotes']['post']['summary'] = 'Create a five-minute route/fare snapshot; destination coordinates required in Google mode'
SPEC['paths']['/admin/fare-settings'] = {'get': operation('Read versioned fare policy and audit history (admin)',protected=True), 'put':operation('Save a validated new fare policy version (admin)',protected=True)}
SPEC['paths']['/admin/fare-settings']['put']['requestBody'] = {'required':True,'content':{'application/json':{'schema':{'type':'object','required':['version','reason','policy'],'properties':{'version':{'type':'integer','minimum':0},'reason':{'type':'string','minLength':1,'maxLength':300},'policy':{'type':'object','description':'Complete policy returned by GET. Includes INR rates, minimum fare, timezone, capped surge, traffic/demand thresholds and scheduled circular zones.'}}}}}}
SPEC['paths']['/admin/revenue-share'] = {'get':operation('Read current and scheduled revenue shares plus immutable audit history (admin)',protected=True), 'put':operation('Save an immediate or future revenue split; percentages must total 100 (admin)',protected=True)}
SPEC['paths']['/admin/revenue-share']['put']['requestBody'] = {'required':True,'content':{'application/json':{'schema':{'type':'object','required':['version','driver_pct','company_pct','reason'],'properties':{'version':{'type':'integer','minimum':0},'driver_pct':{'type':'string','example':'85.00'},'company_pct':{'type':'string','example':'15.00'},'reason':{'type':'string','minLength':1,'maxLength':300},'effective_from':{'type':'string','format':'date-time','nullable':True,'description':'Null for immediately; otherwise future ISO timestamp with timezone, within one year.'}}}}}}
SPEC['paths']['/admin/audit'] = {'get':operation('Search paginated driver/fare/revenue change history (admin only)',protected=True)}
SPEC['paths']['/admin/audit']['get']['parameters'] = [{'name':'page','in':'query','schema':{'type':'integer','minimum':1,'default':1}},{'name':'category','in':'query','schema':{'type':'string','enum':['driver','fares','revenue']}},{'name':'q','in':'query','schema':{'type':'string','maxLength':100}}]
SPEC['paths']['/admin/audit/{category}/{identifier}'] = {'parameters':[{'name':'category','in':'path','required':True,'schema':{'type':'string','enum':['driver','fares','revenue']}},{'name':'identifier','in':'path','required':True,'schema':{'type':'string'}}], 'get':operation('Read before/after values for an admin change (admin only)',protected=True)}
for action in ['accept', 'reject', 'cancel', 'depart', 'arrive', 'start', 'complete']:
    route = '/rides/{ride_id}/' + action
    SPEC['paths'][route] = {'parameters': [{'name': 'ride_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'post': operation(f'{action.capitalize()} a ride with permission and state checks', protected=True)}
SPEC['paths']['/rides/{ride_id}'] = {'parameters': [{'name': 'ride_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'get': operation('Get a ride you participate in (or admin)', protected=True)}
SPEC['paths']['/rides/{ride_id}']['get']['description']='Riders receive their fare and trip details only. Settlement amounts and percentages are returned only to the assigned driver or an admin. Rider workspace/history/booking responses follow the same filtering.'
SPEC['paths']['/admin/drivers/{driver_id}/approve'] = {'parameters': [{'name': 'driver_id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}}], 'post': operation('Approve pending driver and record an audit reason', ['reason'], protected=True)}

SPEC['paths']['/rides/{ride_id}/start']['post'] = operation('Start the assigned waiting trip using the six-digit OTP for this ride', ['otp'], protected=True)
SPEC['paths']['/rides/{ride_id}/start']['post']['requestBody']['content']['application/json']['schema']['properties']['otp'] = {'type':'string','pattern':'^[0-9]{6}$','description':'Provided by the rider at pickup. Five failed attempts per driver per minute in the single-process development limiter.'}
SPEC['paths']['/workspace']['get']['description'] = 'Rider workspaces include trip_otp, the six-digit code for the active ride before it starts (otherwise null). Each ride has a different code. Driver and admin responses never include this code.'

SPEC['components']['securitySchemes']['refreshCookie'] = {'type':'apiKey','in':'cookie','name':'ridez_refresh'}
for action, summary in [('refresh','Rotate the single-use refresh cookie and issue an access token'), ('logout','Revoke the current cookie session, disconnect its sockets and stop new driver requests'), ('logout-all','Revoke all sessions for the signed-in account')]:
    endpoint = operation(summary, protected=action=='logout-all')
    endpoint['parameters'] = [{'name':'X-Session-Request','in':'header','required':True,'schema':{'type':'string','enum':['1']}}]
    endpoint['description'] = 'Send cookies on the same origin. Session endpoints reject cross-site browser origins. Logout preserves active trips. Refresh credentials are HttpOnly and never returned in JSON. Reusing an old refresh credential revokes its session.'
    if action != 'logout-all':
        endpoint['security'] = [{'refreshCookie':[]}]
    SPEC['paths']['/auth/'+action] = {'post':endpoint}
SPEC['paths']['/auth/login']['post']['description'] = 'Creates a revocable server session, returns access_token/expires_in/expires_at/user and sets an HttpOnly SameSite=Lax refresh cookie scoped to /api/v1/auth. Production cookies require HTTPS. Responses are not cached.'

SPEC['paths']['/admin/drivers'] = {'get':operation('Search and paginate driver accounts with status and active trip summaries (admin)',protected=True)}
SPEC['paths']['/admin/drivers']['get']['parameters'] = [{'name':'page','in':'query','schema':{'type':'integer','minimum':1,'default':1}},{'name':'status','in':'query','schema':{'type':'string','enum':['pending','active','suspended','disabled']}},{'name':'q','in':'query','schema':{'type':'string','maxLength':100},'description':'Literal search by name, mobile or permanent code.'}]
for action in ('suspend','reinstate'):
    endpoint = operation(f'{action.capitalize()} a driver with a version guard and immutable review reason (admin)',protected=True)
    endpoint['requestBody'] = {'required':True,'content':{'application/json':{'schema':{'type':'object','required':['version','reason'],'properties':{'version':{'type':'integer','minimum':0,'description':'status_revision from the current driver list'},'reason':{'type':'string','minLength':1,'maxLength':300}}}}}}
    endpoint['description'] = 'Suspension blocks new work but preserves active trips, earnings and sign-in. Suspension reasons are visible to the driver. Reinstatement leaves the driver offline. Exact retries are idempotent; stale versions return 409.'
    SPEC['paths'][f'/admin/drivers/{{driver_id}}/{action}'] = {'parameters':[{'name':'driver_id','in':'path','required':True,'schema':{'type':'integer'}}],'post':endpoint}
SPEC['paths']['/admin/drivers/{driver_id}/approve']['post']['requestBody']['content']['application/json']['schema']['properties']['version'] = {'type':'integer','minimum':0,'description':'Optional for legacy approval clients; new clients should send status_revision.'}
SPEC['components']['schemas']['User']['properties']['status_revision'] = {'type':'integer','minimum':0}
SPEC['info']['version'] = '0.8.0'

SPEC['paths']['/ready'] = {'get':operation('Read deployment readiness: current migration head and live matching loop')}
SPEC['paths']['/ready']['get']['responses']['503'] = {'description':'Database schema or matching worker is not ready'}

SPEC['paths']['/rides/{ride_id}/map'] = {'parameters':[{'name':'ride_id','in':'path','required':True,'schema':{'type':'string'}}], 'get':operation('Read the active Google road route and fresh driver position (rider or assigned driver only)',protected=True)}
SPEC['paths']['/rides/{ride_id}/map']['get']['description'] = 'Google rides only. Before start, returns the pickup-to-destination route. In progress, uses fresh driver GPS as origin; otherwise explicitly falls back to the pickup route without a driver marker. Road geometry is cached in memory for 60 seconds and shared between participants; location metadata refreshes per request. No fare changes. Driver coordinates are excluded after completion/cancellation and from admin/unrelated-user access. Google errors are returned without simulated geometry.'

SPEC['paths']['/admin/drivers/{driver_id}/vehicle'] = {'parameters':[{'name':'driver_id','in':'path','required':True,'schema':{'type':'integer'}}], 'put':operation('Record reviewed car details for a driver (admin only)',protected=True)}
SPEC['paths']['/admin/drivers/{driver_id}/vehicle']['put']['requestBody'] = {'required':True,'content':{'application/json':{'schema':{'type':'object','required':['version','registration','model','color','reason'],'properties':{'version':{'type':'integer','minimum':0,'description':'Current vehicle version, or zero if none'},'registration':{'type':'string','minLength':4,'maxLength':20},'model':{'type':'string','maxLength':80},'color':{'type':'string','maxLength':40},'reason':{'type':'string','maxLength':300}}}}}}
SPEC['paths']['/admin/drivers/{driver_id}/vehicle']['put']['description'] = 'Vehicle updates require a current version and review reason. Active-trip changes and stale versions return 409. A ride snapshots the vehicle when its driver accepts; later profile updates cannot rewrite the trip or receipt. This records admin-reviewed information; no external vehicle verification is performed.'

SPEC['paths']['/rides/{ride_id}/cancel']['post'] = operation('Cancel a searching or pre-start ride as its rider or assigned driver', ['reason'], protected=True)
SPEC['paths']['/rides/{ride_id}/cancel']['post']['requestBody']['content']['application/json']['schema']['properties']['reason'] = {'type':'string','minLength':1,'maxLength':300}
SPEC['paths']['/rides/{ride_id}/cancel']['post']['description'] = 'Allowed only in SEARCHING (rider only), ASSIGNED, ARRIVING or WAITING. A reason is required after assignment. Legacy searching clients may omit it; new clients should always send one. Cancellation atomically records server time/actor/reason, closes invitations, releases participant claims and leaves assigned drivers offline. Existing cancellation retries return the original record unchanged. IN_PROGRESS/completed/expired rides return 409. No payment, refund or fee is processed. The shared cancellation record appears in ride details/history and a recent workspace notice.'

SPEC['paths']['/driver/availability']['post']['description'] = 'While idle, available=true requires a fresh GPS fix and goes online. While assigned, it saves the stay-available-after-trip preference and a fresh GPS fix, but keeps actual availability false until completion. available=false always stops new work and saves an offline preference without cancelling an active ride.'
SPEC['paths']['/rides/{ride_id}/complete']['post']['description'] = 'Completes and allocates earnings once. The active driver returns to availability only with fresh GPS, enabled bookings and a persisted stay-available choice. Offline/logout/suspension intent is respected; retries never re-enable availability.'

_ride_param = [{'name': 'ride_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}]
SPEC['paths']['/rides/{ride_id}/payment-method'] = {'parameters': _ride_param, 'post': operation('Rider chooses CASH or ONLINE for a completed, unpaid ride', ['method'], protected=True)}
SPEC['paths']['/rides/{ride_id}/confirm-cash'] = {'parameters': _ride_param, 'post': operation('Assigned driver confirms cash received; the first confirmation wins and is final', protected=True)}
SPEC['paths']['/workspace']['get']['description'] += ' Driver workspaces include confirmed_earnings (payment confirmed) and pending_earnings (awaiting payment); allocated_earnings remains the total recorded split.'

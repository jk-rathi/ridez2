import base64
import io
from datetime import timedelta
from openpyxl import load_workbook
from app import db
from app.models import Ride
from app.location_service import utcnow
from test_auth import app, client
from test_rides import actors, prepare, book, post
from test_mock_payments import completed


def get(client, actors, path, actor='admin'):
    return client.get('/api/v1' + path, headers=actors[actor]['headers'])


def test_analytics_is_admin_only_and_validates_dates(client, actors):
    assert get(client, actors, '/admin/analytics', 'rider').status_code == 403
    assert get(client, actors, '/admin/analytics/export', 'driver').status_code == 403
    for query in ['from=2026-13-01', 'from=2026-02-10&to=2026-02-01', 'from=2024-01-01&to=2026-01-01', 'to=yesterday']:
        assert get(client, actors, f'/admin/analytics?{query}').status_code == 400, query


def test_kpis_series_and_breakdowns(client, app, actors):
    ride = completed(client, actors)
    assert post(client, actors, 'rider', f"/rides/{ride['id']}/payment-method", method='CASH').status_code == 200
    assert post(client, actors, 'driver', f"/rides/{ride['id']}/confirm-cash").status_code == 200
    cancelled = book(client, actors, 'other')
    assert post(client, actors, 'other', f"/rides/{cancelled['id']}/cancel", reason='Plans changed').status_code == 200
    data = get(client, actors, '/admin/analytics').json
    k = data['kpis']
    assert data['range']['days'] == 30 and data['range']['timezone'] == 'Asia/Kolkata'
    assert k['requested_rides'] == 2 and k['completed_rides'] == 1
    assert k['gross_fares'] == ride['quote']['total'] and k['average_fare'] == ride['quote']['total']
    assert k['cancellation_rate_pct'] == 50.0 and k['requested_change_pct'] is None
    assert float(k['company_revenue']) + float(k['driver_earnings']) == float(ride['quote']['total'])
    assert len(data['daily']) == 30 and sum(day['requested'] for day in data['daily']) == 2
    assert data['daily'][-1]['gross_fares'] == ride['quote']['total']
    assert sum(item['requests'] for item in data['hourly']) == 2 and len(data['hourly']) == 24
    assert {item['key']: item['rides'] for item in data['outcomes']} == {'COMPLETED': 1, 'CANCELLED': 1, 'NO_DRIVER_FOUND': 0, 'ACTIVE': 0}
    assert {item['key']: item['rides'] for item in data['payments']} == {'CASH': 1, 'ONLINE': 0, 'PENDING': 0}


def test_date_filter_excludes_rides_outside_range_and_compares_previous_period(client, app, actors):
    first = completed(client, actors)
    with app.app_context():
        ride = db.session.get(Ride, first['id'])
        ride.requested_at -= timedelta(days=10)
        ride.completed_at -= timedelta(days=10)
        db.session.commit()
    completed_again = completed(client, actors)
    today = get(client, actors, '/admin/analytics').json['range']['end']
    week = get(client, actors, f'/admin/analytics?from={today}&to={today}').json['kpis']
    assert week['completed_rides'] == 1 and week['gross_fares'] == completed_again['quote']['total']
    assert get(client, actors, f'/admin/analytics?to={today}').json['kpis']['completed_rides'] == 2


def test_excel_export_has_every_sheet_and_ride_row(client, app, actors):
    ride = completed(client, actors)
    response = get(client, actors, '/admin/analytics/export')
    assert response.status_code == 200
    payload = response.json
    assert payload['filename'].startswith('ridez-report-') and payload['filename'].endswith('.xlsx') and payload['rides'] == 1
    book_ = load_workbook(io.BytesIO(base64.b64decode(payload['content_base64'])))
    assert book_.sheetnames == ['Summary', 'Daily', 'Rides', 'Hourly demand']
    rides = list(book_['Rides'].iter_rows(values_only=True))
    assert rides[0][:3] == ('Ride ID', 'Requested at', 'Status') and rides[1][0] == ride['id'] and rides[1][2] == 'Completed'
    assert 'rider' in rides[1][3] and float(rides[1][8]) == float(ride['quote']['total'])
    assert not any('+91' in str(value) for row in rides for value in row), 'mobile numbers must not be exported'
    summary = dict(book_['Summary'].iter_rows(values_only=True))
    assert summary['Rides completed'] == 1 and len(list(book_['Daily'].iter_rows())) == 31

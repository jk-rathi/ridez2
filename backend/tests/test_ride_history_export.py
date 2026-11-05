import base64
import io
from openpyxl import load_workbook
from test_auth import app, client
from test_rides import actors, prepare, book, post
from test_mock_payments import completed


def export(client, actors, actor, query=''):
    response = client.get(f'/api/v1/ride-history/export{query}', headers=actors[actor]['headers'])
    assert response.status_code == 200, response.json
    sheet = load_workbook(io.BytesIO(base64.b64decode(response.json['content_base64'])))['Ride history']
    rows = list(sheet.iter_rows(values_only=True))
    return response.json, rows[0], [row for row in rows[1:] if row and row[-1] and len(str(row[-1])) == 36]


def test_requires_sign_in(client):
    assert client.get('/api/v1/ride-history/export').status_code == 401


def test_rider_gets_only_own_rides_without_revenue_split(client, actors):
    mine = completed(client, actors)
    prepare(client, actors, 'second')
    other = book(client, actors, 'other')
    meta, header, rows = export(client, actors, 'rider')
    assert meta['rides'] == 1 and meta['filename'].startswith('ridez-ride-history-')
    assert [row[-1] for row in rows] == [mine['id']] and other['id'] not in str(rows)
    assert 'Driver' in header and 'Rider' not in header
    assert not {'Your share', 'Your earnings', 'Driver amount', 'Company amount'} & set(header)
    assert float(rows[0][header.index('Fare')]) == float(mine['quote']['total'])


def test_driver_gets_own_trips_and_own_earnings_only(client, actors):
    ride = completed(client, actors)
    meta, header, rows = export(client, actors, 'driver')
    assert meta['rides'] == 1 and 'Rider' in header and 'Driver' not in header
    assert 'Your earnings' in header and 'Company amount' not in header
    assert rows[0][header.index('Your earnings')] is not None
    assert export(client, actors, 'second')[0]['rides'] == 0


def test_admin_gets_every_ride_with_split_and_range_filter(client, actors):
    completed(client, actors)
    book(client, actors, 'other')
    meta, header, rows = export(client, actors, 'admin')
    assert meta['rides'] == 2 and {'Rider', 'Driver', 'Driver amount', 'Company amount'} <= set(header)
    assert export(client, actors, 'admin', '?from=2020-01-01&to=2020-01-31')[0]['rides'] == 0
    assert client.get('/api/v1/ride-history/export?from=2026-02-10&to=2026-02-01', headers=actors['admin']['headers']).status_code == 400

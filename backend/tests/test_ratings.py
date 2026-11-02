import json
from test_auth import app, client
from test_rides import actors, post, prepare, book
from test_mock_payments import completed


def ride_view(client, actors, role, ride):
    return client.get('/api/v1/rides/'+ride['id'], headers=actors[role]['headers']).json['ride']


def rate(client, actors, role, ride, **data):
    return post(client, actors, role, f"/rides/{ride['id']}/rating", **data)


def test_two_way_ratings_update_averages(client, app, actors):
    ride = completed(client, actors)
    assert ride_view(client, actors, 'rider', ride)['my_rating'] is None
    assert ride_view(client, actors, 'rider', ride)['driver']['rating'] == {'average': None, 'count': 0}
    rider = rate(client, actors, 'rider', ride, stars=4, tags=['Clean car', 'Friendly'], comment='  Nice trip  ')
    assert rider.status_code == 200
    assert rider.json['rating'] | {'created_at': None} == {'rater_role': 'rider', 'stars': 4, 'tags': ['Clean car', 'Friendly'], 'comment': 'Nice trip', 'created_at': None}
    assert rate(client, actors, 'driver', ride, stars=5).status_code == 200
    seen_by_rider = ride_view(client, actors, 'rider', ride)
    assert seen_by_rider['my_rating']['stars'] == 4
    assert seen_by_rider['driver']['rating'] == {'average': '4.0', 'count': 1}
    assert ride_view(client, actors, 'driver', ride)['rider']['rating'] == {'average': '5.0', 'count': 1}
    assert client.get('/api/v1/workspace', headers=actors['driver']['headers']).json['my_rating_summary'] == {'average': '4.0', 'count': 1}
    drivers = client.get('/api/v1/admin/drivers', headers=actors['admin']['headers']).json['items']
    assert next(d for d in drivers if d['id'] == actors['driver']['id'])['rating'] == {'average': '4.0', 'count': 1}


def test_comments_hidden_from_the_rated_person_but_visible_to_admin(client, app, actors):
    ride = completed(client, actors)
    rate(client, actors, 'rider', ride, stars=2, tags=['Late'], comment='Driver was very late')
    rate(client, actors, 'driver', ride, stars=3, comment='Rider kept me waiting')
    for role, hidden in (('driver', 'Driver was very late'), ('rider', 'Rider kept me waiting')):
        responses = [client.get('/api/v1/workspace', headers=actors[role]['headers']).json, ride_view(client, actors, role, ride)]
        assert hidden not in json.dumps(responses) and 'ratings' not in responses[1]
    admin = ride_view(client, actors, 'admin', ride)['ratings']
    assert {(r['rater_role'], r['stars'], r['comment']) for r in admin} == {('rider', 2, 'Driver was very late'), ('driver', 3, 'Rider kept me waiting')}


def test_ratings_are_final_and_validated(client, app, actors):
    ride = completed(client, actors)
    for data in ({}, {'stars': 0}, {'stars': 6}, {'stars': True}, {'stars': '5'}, {'stars': 5, 'tags': ['Rude driver']},
                 {'stars': 5, 'tags': 'Late'}, {'stars': 5, 'comment': 'x'*301}):
        assert rate(client, actors, 'rider', ride, **data).status_code == 400
    # Rider-only tags are not valid for drivers.
    assert rate(client, actors, 'driver', ride, stars=4, tags=['Clean car']).status_code == 400
    assert rate(client, actors, 'rider', ride, stars=5).status_code == 200
    assert rate(client, actors, 'rider', ride, stars=5).status_code == 200
    assert rate(client, actors, 'rider', ride, stars=1).status_code == 409
    assert ride_view(client, actors, 'rider', ride)['my_rating']['stars'] == 5


def test_only_participants_rate_completed_rides(client, app, actors):
    ride = completed(client, actors)
    assert rate(client, actors, 'other', ride, stars=5).status_code == 404
    assert rate(client, actors, 'second', ride, stars=5).status_code == 404
    assert rate(client, actors, 'admin', ride, stars=5).status_code == 403
    assert client.post(f"/api/v1/rides/{ride['id']}/rating", json={'stars': 5}).status_code == 401
    pending = book(client, actors)
    assert rate(client, actors, 'rider', pending, stars=5).status_code == 409


def test_invitation_shows_rider_rating_to_driver(client, app, actors):
    first = completed(client, actors)
    rate(client, actors, 'driver', first, stars=4)
    second = book(client, actors)
    invitations = client.get('/api/v1/workspace', headers=actors['driver']['headers']).json['invitations']
    assert next(i for i in invitations if i['id'] == second['id'])['rider']['rating'] == {'average': '4.0', 'count': 1}

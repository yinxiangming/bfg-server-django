"""What a shopper is allowed to leave out of a saved address.

The postcode is the one that mattered: every form that collects an address
labels it optional -- the storefront's and the mini-program's alike -- while the
model made it mandatory, so the save came back 400 and the shopper saw only
"could not save". WeChat review hit it with a form of ones and a blank postcode
and rejected the package for it.
"""

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Customer, User, Workspace

ADDRESSES_URL = '/api/v1/store/addresses/'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Address WS', slug='address-ws', is_active=True)


@pytest.fixture
def shopper(workspace):
    user = User.objects.create_user(username='addr-shopper', email='addr@test.com', password='x')
    Customer.objects.create(workspace=workspace, user=user, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


def post(client, **overrides):
    payload = {
        'full_name': 'Jacky Chen',
        'phone': '0211234567',
        'address_line1': '3 Oracle Drive',
        'city': 'Auckland',
        'country': 'NZ',
    }
    payload.update(overrides)
    return client.post(ADDRESSES_URL, payload, format='json')


def test_an_address_saves_without_a_postcode(shopper):
    response = post(shopper)

    assert response.status_code == 201, response.data
    assert response.data['postal_code'] == ''


def test_an_empty_postcode_is_not_a_blank_field_error(shopper):
    # The mini-program omits the key; the web form sends ''. Both are the same
    # shopper leaving the same optional field alone.
    response = post(shopper, postal_code='')

    assert response.status_code == 201, response.data


def test_a_postcode_is_still_kept_when_given(shopper):
    response = post(shopper, postal_code='0632')

    assert response.status_code == 201, response.data
    assert response.data['postal_code'] == '0632'


def test_the_city_is_still_required(shopper):
    # Optional does not mean optional all round: without a city there is no
    # address, and the form asks for it before it asks the server.
    response = post(shopper, city='')

    assert response.status_code == 400
    assert 'city' in response.data


def test_the_saved_address_comes_back_in_the_list(shopper):
    post(shopper)

    body = shopper.get(ADDRESSES_URL).json()

    results = body['results'] if isinstance(body, dict) else body
    assert [a['address_line1'] for a in results] == ['3 Oracle Drive']

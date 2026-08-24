"""The note a shopper leaves at checkout has to come back to them.

``cart/checkout/`` has always accepted ``customer_note`` and stored it, but the
storefront order serializer never returned it — so the shopper had no way to
tell whether the note was recorded, and the order-detail page had nothing to
render. ``admin_note`` stays internal.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Address, Customer, User, Workspace
from bfg.shop.models import Product, Store

CART_URL = '/api/v1/store/cart/'
NOTE = '请放在门口，收货前电话联系'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Note WS', slug='note-ws', is_active=True)


@pytest.fixture
def store(workspace):
    return Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)


@pytest.fixture
def product(workspace):
    return Product.objects.create(
        workspace=workspace,
        name='Compact Washing Machine',
        slug='compact-washing-machine',
        price=Decimal('339.00'),
        is_active=True,
        track_inventory=False,
    )


@pytest.fixture
def shopper(workspace):
    user = User.objects.create_user(username='note-shopper', email='note@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client, customer


@pytest.fixture
def address(workspace, shopper):
    _, customer = shopper
    return Address.objects.create(
        workspace=workspace,
        content_object=customer,
        full_name='微信 会员',
        phone='0211234567',
        address_line1='12 Queen St',
        city='Auckland',
        postal_code='1010',
        country='NZ',
    )


def place_order(client, store, product, address, note=None):
    added = client.post(f'{CART_URL}add_item/', {'product': product.id, 'quantity': 1}, format='json')
    assert added.status_code == 200, added.data
    payload = {
        'store': store.id,
        'shipping_address': address.id,
        'billing_address': address.id,
    }
    if note is not None:
        payload['customer_note'] = note
    return client.post(f'{CART_URL}checkout/', payload, format='json')


def test_checkout_returns_the_note_it_was_given(store, product, address, shopper):
    client, _ = shopper

    response = place_order(client, store, product, address, note=NOTE)

    assert response.status_code == 201, response.data
    assert response.data['customer_note'] == NOTE


def test_the_note_is_still_there_when_the_order_is_read_back(store, product, address, shopper):
    """The order-detail page fetches the order separately from the checkout response."""
    client, _ = shopper
    order_id = place_order(client, store, product, address, note=NOTE).data['id']

    response = client.get(f'/api/v1/store/orders/{order_id}/')

    assert response.status_code == 200, response.data
    assert response.data['customer_note'] == NOTE


def test_an_order_placed_without_a_note_reports_an_empty_one(store, product, address, shopper):
    """The client renders the note section conditionally, so absent must not be null."""
    client, _ = shopper

    response = place_order(client, store, product, address)

    assert response.status_code == 201, response.data
    assert response.data['customer_note'] == ''


def test_the_internal_admin_note_is_not_exposed(store, product, address, shopper):
    client, _ = shopper

    response = place_order(client, store, product, address, note=NOTE)

    assert 'admin_note' not in response.data

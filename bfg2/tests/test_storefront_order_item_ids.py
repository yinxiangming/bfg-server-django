"""A customer's order lists its items with their ids.

A return line names the order item it sends back (``ReturnLineItem.order_item``),
and the customer's own order endpoints are the only place a customer can read
their items from. Without the id a customer could open a return request but
never say what was in it.
"""

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from bfg.common.models import Customer, User, Workspace
from bfg.shop.models import Order, OrderItem, Product, Store


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    """Workspace membership is cached per user id, and ids are reused between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def purchase(db):
    workspace = Workspace.objects.create(name='item-ids', slug='item-ids', is_active=True)
    user = User.objects.create_user(username='item-ids-shopper', email='item-ids@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    # Store.objects is tenant-scoped and empty outside a request; look past the scope.
    store = Store.all_objects.filter(workspace=workspace).first() or Store.objects.create(
        workspace=workspace, name='Main', code='main', is_active=True,
    )
    product = Product.objects.create(
        workspace=workspace, name='Widget', slug='widget', price=Decimal('10.00'), track_inventory=False,
    )
    order = Order.objects.create(
        workspace=workspace, store=store, customer=customer, order_number='ORD-ITEM-IDS-1',
        subtotal=Decimal('20.00'), total=Decimal('20.00'),
    )
    item = OrderItem.objects.create(
        order=order, product=product, product_name=product.name, quantity=2,
        price=Decimal('10.00'), subtotal=Decimal('20.00'),
    )

    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client, order, item


def test_order_items_carry_their_ids(purchase):
    client, order, item = purchase

    detail = client.get(f'/api/v1/me/orders/{order.id}/')
    listing = client.get('/api/v1/me/orders/')

    assert detail.status_code == 200, detail.data
    assert [row['id'] for row in detail.data['items']] == [item.id]
    assert listing.status_code == 200, listing.data
    rows = listing.data['results'] if isinstance(listing.data, dict) else listing.data
    assert [row['id'] for row in rows[0]['items']] == [item.id]


def test_an_item_id_from_the_order_names_a_return_line(purchase):
    client, order, _ = purchase
    item_id = client.get(f'/api/v1/me/orders/{order.id}/').data['items'][0]['id']

    created = client.post('/api/v1/shop/returns/', {'order': order.id, 'reason_category': 'faulty'}, format='json')
    assert created.status_code == 201, created.data

    line = client.post(
        '/api/v1/shop/return-items/',
        {'return_request': created.data['id'], 'order_item': item_id, 'quantity': 1},
        format='json',
    )

    assert line.status_code == 201, line.data
    assert line.data['order_item'] == item_id

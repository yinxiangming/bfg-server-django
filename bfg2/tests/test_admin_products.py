"""The admin's view of the catalogue: narrowing it, and deleting from it.

wxstore holds 453 products of which 359 are unpublished. The list is
server-paginated, so both of those numbers have to come from the server —
a filter applied to the twenty rows already fetched is not a filter.
"""

import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from bfg.common.models import Customer, StaffMember, StaffRole, User, Workspace
from bfg.shop.models import Order, OrderItem, Product, Store

LIST_URL = '/api/v1/shop/admin/products/'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Catalogue WS', slug='catalogue-ws', is_active=True)


@pytest.fixture
def client(db, workspace):
    user = User.objects.create_user(username='cat-staff', email='staff@test.com', password='testpass123')
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


def make_product(workspace, name, slug, **kwargs):
    return Product.objects.create(
        workspace=workspace, name=name, slug=slug,
        price=kwargs.pop('price', Decimal('9.99')), track_inventory=False, **kwargs
    )


def names(response):
    body = response.json()
    rows = body['results'] if isinstance(body, dict) else body
    return {row['name'] for row in rows}


@pytest.fixture
def catalogue(workspace):
    return {
        'live': make_product(workspace, 'Live', 'live', is_active=True),
        'draft': make_product(workspace, 'Draft', 'draft', is_active=False),
        'starred': make_product(workspace, 'Starred', 'starred', is_active=True, is_featured=True),
    }


def test_unfiltered_list_shows_drafts_too(client, catalogue):
    """The admin list is the whole catalogue; that is the point of it."""
    assert names(client.get(LIST_URL)) == {'Live', 'Draft', 'Starred'}


def test_is_active_false_finds_the_drafts(client, catalogue):
    """The half that never worked: `featured` was the only boolean the server
    read, so picking "Inactive" in the admin changed nothing at all."""
    assert names(client.get(LIST_URL, {'is_active': 'false'})) == {'Draft'}


def test_is_active_true_finds_the_published(client, catalogue):
    assert names(client.get(LIST_URL, {'is_active': 'true'})) == {'Live', 'Starred'}


def test_featured_filters_both_ways(client, catalogue):
    """`featured=true` worked; `featured=false` was silently ignored."""
    assert names(client.get(LIST_URL, {'is_featured': 'true'})) == {'Starred'}
    assert names(client.get(LIST_URL, {'is_featured': 'false'})) == {'Live', 'Draft'}
    # The older spelling still answers, so existing callers keep working.
    assert names(client.get(LIST_URL, {'featured': 'true'})) == {'Starred'}


def test_an_absent_filter_is_not_a_false_one(client, catalogue):
    """`?is_active=` must not read as "show me the drafts"."""
    assert names(client.get(LIST_URL, {'is_active': ''})) == {'Live', 'Draft', 'Starred'}


def test_the_public_list_never_exposes_drafts(db, workspace, catalogue):
    """The storefront viewset narrows to active before the shared filter runs,
    so `is_active=false` there is empty rather than a way in."""
    anon = APIClient()
    anon.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    assert names(anon.get('/api/v1/shop/products/', {'is_active': 'false'})) == set()
    assert names(anon.get('/api/v1/shop/products/')) == {'Live', 'Starred'}


def test_a_product_nobody_ordered_deletes(client, catalogue):
    response = client.delete(f'{LIST_URL}{catalogue["draft"].id}/')

    assert response.status_code == 204
    assert not Product.all_objects.filter(id=catalogue['draft'].id).exists()


def test_an_ordered_product_is_refused_with_a_reason(client, workspace, catalogue):
    """OrderItem.product is PROTECT, so Django raised ProtectedError and the
    client got a bare 500 — deleting a product appeared to work at random."""
    user = User.objects.create_user(username='buyer', email='buyer@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user)
    store = Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)
    product = catalogue['live']
    order = Order.objects.create(
        workspace=workspace, customer=customer, store=store, order_number='ORD-1',
        subtotal=product.price, total=product.price,
    )
    OrderItem.objects.create(
        order=order, product=product, product_name=product.name, quantity=1,
        price=product.price, subtotal=product.price,
    )

    response = client.delete(f'{LIST_URL}{product.id}/')

    assert response.status_code == 409, response.data
    assert response.data['code'] == 'product_in_orders'
    assert response.data['order_count'] == 1
    assert Product.all_objects.filter(id=product.id).exists()

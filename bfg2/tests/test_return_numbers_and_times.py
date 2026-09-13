"""Return numbers, and when a return moved through its workflow.

``return_number`` was unique across every workspace while each workspace counted
its own returns to build it, so the second shop to open a return on a given day
collided with the first. Within one workspace, deleting a return shrank the
count and handed out a number that was still in use.

``approve`` and ``process_refund`` stamped ``approved_at`` and ``refunded_at``,
which the model did not have, so those times were silently dropped.
"""

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from bfg.common.models import Customer, StaffMember, StaffRole, User, Workspace
from bfg.shop.models import Order, OrderItem, Product, Return, Store

RETURNS_URL = '/api/v1/shop/returns/'


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    """Workspace membership is cached per user id, and ids are reused between tests."""
    cache.clear()
    yield
    cache.clear()


def make_workspace(slug):
    return Workspace.objects.create(name=slug, slug=slug, is_active=True)


def signed_in(user, workspace):
    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


def staff_of(workspace):
    user = User.objects.create_user(username=f'staff-{workspace.slug}', email=f'staff-{workspace.slug}@test.com', password='x')
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return signed_in(user, workspace)


def make_order(workspace, number):
    user = User.objects.create_user(username=f'shopper-{number.lower()}', email=f'{number.lower()}@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    # Store.objects is tenant-scoped and empty outside a request; look past the scope.
    store = Store.all_objects.filter(workspace=workspace).first() or Store.objects.create(
        workspace=workspace, name='Main', code='main', is_active=True,
    )
    product = Product.objects.create(
        workspace=workspace, name=f'Widget {number}', slug=f'widget-{number.lower()}',
        price=Decimal('10.00'), track_inventory=False,
    )
    order = Order.objects.create(
        workspace=workspace, store=store, customer=customer, order_number=number,
        subtotal=Decimal('10.00'), total=Decimal('10.00'),
    )
    OrderItem.objects.create(
        order=order, product=product, product_name=product.name, quantity=1,
        price=Decimal('10.00'), subtotal=Decimal('10.00'),
    )
    return order


def open_return(client, order):
    response = client.post(RETURNS_URL, {'order': order.id, 'reason_category': 'faulty'}, format='json')
    assert response.status_code == 201, response.data
    return response.data


@pytest.fixture
def workspace(db):
    return make_workspace('return-times')


@pytest.fixture
def staff(workspace):
    return staff_of(workspace)


# --- numbers -----------------------------------------------------------------

def test_two_workspaces_each_open_their_first_return_on_the_same_day(db):
    first_shop, second_shop = make_workspace('first-shop'), make_workspace('second-shop')

    first = open_return(staff_of(first_shop), make_order(first_shop, 'ORD-FIRST-1'))
    second = open_return(staff_of(second_shop), make_order(second_shop, 'ORD-SECOND-1'))

    # Each shop numbers its own returns, so the same number in both is expected.
    assert first['return_number'] == second['return_number']


def test_a_deleted_return_does_not_hand_its_number_out_again(workspace, staff):
    doomed = open_return(staff, make_order(workspace, 'ORD-NUM-1'))
    kept = open_return(staff, make_order(workspace, 'ORD-NUM-2'))
    assert staff.delete(f"{RETURNS_URL}{doomed['id']}/").status_code == 204

    latest = open_return(staff, make_order(workspace, 'ORD-NUM-3'))

    assert latest['return_number'] != kept['return_number']


# --- times ---------------------------------------------------------------------

def test_approving_a_return_records_when(workspace, staff):
    created = open_return(staff, make_order(workspace, 'ORD-APPROVE-1'))

    response = staff.post(f"{RETURNS_URL}{created['id']}/approve/", {}, format='json')

    assert response.status_code == 200, response.data
    assert response.data['approved_at'] is not None
    assert Return.objects.get(pk=created['id']).approved_at is not None


def test_refunding_a_return_records_when(workspace, staff):
    created = open_return(staff, make_order(workspace, 'ORD-REFUND-1'))
    assert staff.post(f"{RETURNS_URL}{created['id']}/approve/", {}, format='json').status_code == 200

    response = staff.post(f"{RETURNS_URL}{created['id']}/process_refund/", {}, format='json')

    assert response.status_code == 200, response.data
    assert response.data['refunded_at'] is not None
    assert Return.objects.get(pk=created['id']).refunded_at is not None


def test_moving_a_return_along_by_editing_it_records_when_once(workspace, staff):
    created = open_return(staff, make_order(workspace, 'ORD-EDIT-1'))
    url = f"{RETURNS_URL}{created['id']}/"

    approved = staff.patch(url, {'status': 'approved'}, format='json')
    assert approved.status_code == 200, approved.data
    first_stamp = Return.objects.get(pk=created['id']).approved_at
    assert first_stamp is not None

    # Re-saving the same status later keeps the original time.
    assert staff.patch(url, {'status': 'approved', 'admin_note': 'Label sent'}, format='json').status_code == 200
    assert Return.objects.get(pk=created['id']).approved_at == first_stamp

    refunded = staff.patch(url, {'status': 'refunded'}, format='json')
    assert refunded.status_code == 200, refunded.data
    assert refunded.data['refunded_at'] is not None


def test_the_times_cannot_be_written_directly(workspace, staff):
    created = open_return(staff, make_order(workspace, 'ORD-DIRECT-1'))

    response = staff.patch(
        f"{RETURNS_URL}{created['id']}/",
        {'approved_at': '2020-01-01T00:00:00Z', 'refunded_at': '2020-01-01T00:00:00Z'},
        format='json',
    )

    assert response.status_code == 200, response.data
    stored = Return.objects.get(pk=created['id'])
    assert (stored.approved_at, stored.refunded_at) == (None, None)


# --- listing -------------------------------------------------------------------

def test_the_returns_of_one_order_can_be_listed(workspace, staff):
    order = make_order(workspace, 'ORD-LIST-1')
    wanted = open_return(staff, order)
    open_return(staff, make_order(workspace, 'ORD-LIST-2'))

    response = staff.get(RETURNS_URL, {'order': order.id})

    assert response.status_code == 200, response.data
    rows = response.data['results'] if isinstance(response.data, dict) else response.data
    assert [row['id'] for row in rows] == [wanted['id']]
    assert {'approved_at', 'refunded_at', 'closed_at'} <= set(rows[0])

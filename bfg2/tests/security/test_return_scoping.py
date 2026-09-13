"""A shopper's returns belong to that shopper.

A return request says what a customer bought, how many, and why they are sending
it back. The return list was already narrowed to the signed-in customer, but its
line items were not: any signed-in account in the workspace could list every
line, rewrite or delete it, and add lines to somebody else's request. The return
itself was writable in full by its owner, so a shopper could mark their own
request refunded or move it onto another order.

A shopper may open a request for their own order, add and change its lines, and
edit their note -- while the request is still open. Everything after that is the
shop's decision.
"""

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from bfg.common.models import Customer, StaffMember, StaffRole, User, Workspace
from bfg.shop.models import Order, OrderItem, Product, Return, ReturnLineItem, Store

RETURNS_URL = '/api/v1/shop/returns/'
ITEMS_URL = '/api/v1/shop/return-items/'


@pytest.fixture(autouse=True)
def _fresh_access_cache():
    """Workspace membership is cached per user id, and ids are reused between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Returns WS', slug='returns-ws', is_active=True)


@pytest.fixture
def other_workspace(db):
    return Workspace.objects.create(name='Other Returns WS', slug='other-returns-ws', is_active=True)


@pytest.fixture
def store(workspace):
    return Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)


def signed_in(user, workspace):
    # A session login, so the workspace middleware sees who is asking --
    # force_authenticate only reaches the view, after membership is decided.
    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


def make_customer(workspace, username):
    user = User.objects.create_user(username=username, email=f'{username}@test.com', password='x')
    return Customer.objects.create(workspace=workspace, user=user, is_active=True)


def make_order(workspace, store, customer, number, quantity=2):
    product = Product.objects.create(
        workspace=workspace, name=f'Widget {number}', slug=f'widget-{number.lower()}',
        price=Decimal('10.00'), track_inventory=False,
    )
    order = Order.objects.create(
        workspace=workspace, store=store, customer=customer, order_number=number,
        subtotal=Decimal('10.00') * quantity, total=Decimal('10.00') * quantity,
    )
    item = OrderItem.objects.create(
        order=order, product=product, product_name=product.name, quantity=quantity,
        price=Decimal('10.00'), subtotal=Decimal('10.00') * quantity,
    )
    return order, item


def make_return(workspace, order, item, number, status='open'):
    return_request = Return.objects.create(
        workspace=workspace, order=order, customer=order.customer, return_number=number, status=status,
    )
    line = ReturnLineItem.objects.create(return_request=return_request, order_item=item, quantity=1, reason='faulty')
    return return_request, line


@pytest.fixture
def alice(workspace):
    return make_customer(workspace, 'alice')


@pytest.fixture
def bob(workspace):
    return make_customer(workspace, 'bob')


@pytest.fixture
def alices_return(workspace, store, alice):
    order, item = make_order(workspace, store, alice, 'ORD-ALICE-1')
    return_request, line = make_return(workspace, order, item, 'RET-ALICE-1')
    return return_request, line, item


@pytest.fixture
def bobs_return(workspace, store, bob):
    order, item = make_order(workspace, store, bob, 'ORD-BOB-1')
    return_request, line = make_return(workspace, order, item, 'RET-BOB-1')
    return return_request, line, item


@pytest.fixture
def staff_client(workspace):
    user = User.objects.create_user(username='returns-staff', email='returns-staff@test.com', password='x')
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return signed_in(user, workspace)


def foreign_return(other_workspace, username, number):
    foreigner = make_customer(other_workspace, username)
    store = Store.objects.create(workspace=other_workspace, name='Main', code='main', is_active=True)
    order, item = make_order(other_workspace, store, foreigner, number)
    return_request, _ = make_return(other_workspace, order, item, f'RET-{number}')
    return order, item, return_request


def ids(response):
    body = response.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    return {row['id'] for row in rows}


# --- return line items -------------------------------------------------------

def test_a_customer_lists_only_the_lines_of_their_own_returns(workspace, bob, alices_return, bobs_return):
    response = signed_in(bob.user, workspace).get(ITEMS_URL)

    assert response.status_code == 200
    assert ids(response) == {bobs_return[1].id}


@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_another_customers_line_is_out_of_reach(workspace, bob, alices_return, method):
    _, line, _ = alices_return
    client = signed_in(bob.user, workspace)
    url = f'{ITEMS_URL}{line.id}/'

    if method == 'get':
        response = client.get(url)
    elif method == 'patch':
        response = client.patch(url, {'quantity': 2}, format='json')
    else:
        response = client.delete(url)

    assert response.status_code == 404
    line.refresh_from_db()
    assert line.quantity == 1


def test_a_customer_cannot_add_lines_to_another_customers_return(workspace, bob, alices_return):
    return_request, _, item = alices_return

    response = signed_in(bob.user, workspace).post(
        ITEMS_URL, {'return_request': return_request.id, 'order_item': item.id, 'quantity': 1}, format='json',
    )

    assert response.status_code == 400
    assert return_request.items.count() == 1


def test_a_customer_adds_a_line_to_their_own_open_return(workspace, alice, alices_return):
    return_request, line, item = alices_return
    line.delete()

    response = signed_in(alice.user, workspace).post(
        ITEMS_URL,
        {'return_request': return_request.id, 'order_item': item.id, 'quantity': 2,
         'reason': 'faulty', 'restock_action': 'restock'},
        format='json',
    )

    assert response.status_code == 201, response.data
    created = return_request.items.get()
    assert created.quantity == 2
    # What happens to the returned stock is the shop's call, not the shopper's.
    assert created.restock_action == 'no_restock'


def test_lines_stop_changing_once_the_shop_has_reviewed_the_return(workspace, alice, alices_return):
    return_request, line, item = alices_return
    Return.objects.filter(pk=return_request.pk).update(status='approved')
    client = signed_in(alice.user, workspace)

    created = client.post(
        ITEMS_URL, {'return_request': return_request.id, 'order_item': item.id, 'quantity': 1}, format='json',
    )
    changed = client.patch(f'{ITEMS_URL}{line.id}/', {'quantity': 2}, format='json')
    deleted = client.delete(f'{ITEMS_URL}{line.id}/')

    assert (created.status_code, changed.status_code, deleted.status_code) == (400, 400, 400)
    line.refresh_from_db()
    assert line.quantity == 1
    assert return_request.items.count() == 1


def test_a_line_must_come_from_the_returned_order(workspace, store, alice, alices_return):
    return_request, _, _ = alices_return
    _, other_item = make_order(workspace, store, alice, 'ORD-ALICE-2')

    response = signed_in(alice.user, workspace).post(
        ITEMS_URL, {'return_request': return_request.id, 'order_item': other_item.id, 'quantity': 1}, format='json',
    )

    assert response.status_code == 400
    assert return_request.items.count() == 1


def test_a_return_cannot_hold_more_of_an_item_than_was_bought(workspace, alice, alices_return):
    # Two were bought and one is already on the request.
    return_request, _, item = alices_return

    response = signed_in(alice.user, workspace).post(
        ITEMS_URL, {'return_request': return_request.id, 'order_item': item.id, 'quantity': 2}, format='json',
    )

    assert response.status_code == 400
    assert return_request.items.count() == 1


def test_staff_add_a_line_the_way_the_order_page_does(workspace, staff_client, alices_return):
    return_request, line, item = alices_return
    line.delete()

    response = staff_client.post(
        ITEMS_URL,
        {'return_request': return_request.id, 'order_item': item.id, 'quantity': 2,
         'reason': 'faulty', 'restock_action': 'restock'},
        format='json',
    )

    assert response.status_code == 201, response.data
    assert return_request.items.get().restock_action == 'restock'


def test_staff_cannot_attach_a_line_to_another_workspaces_return(other_workspace, staff_client):
    _, item, return_request = foreign_return(other_workspace, 'foreigner', 'ORD-FOREIGN-1')

    response = staff_client.post(
        ITEMS_URL, {'return_request': return_request.id, 'order_item': item.id, 'quantity': 1}, format='json',
    )

    assert response.status_code == 400
    assert return_request.items.count() == 1


# --- returns -------------------------------------------------------------------

def test_another_customer_cannot_see_or_change_a_return(workspace, bob, alices_return):
    return_request, _, _ = alices_return
    client = signed_in(bob.user, workspace)
    url = f'{RETURNS_URL}{return_request.id}/'

    assert client.get(url).status_code == 404
    assert client.patch(url, {'customer_note': 'mine now'}, format='json').status_code == 404
    return_request.refresh_from_db()
    assert return_request.customer_note == ''


def test_a_customer_cannot_mark_their_own_return_refunded(workspace, alice, alices_return):
    return_request, _, _ = alices_return

    response = signed_in(alice.user, workspace).patch(
        f'{RETURNS_URL}{return_request.id}/', {'status': 'refunded'}, format='json',
    )

    assert response.status_code == 403
    return_request.refresh_from_db()
    assert return_request.status == 'open'


def test_a_customer_cannot_move_their_return_onto_someone_elses_order(workspace, store, alice, bob, alices_return):
    return_request, _, _ = alices_return
    bobs_order, _ = make_order(workspace, store, bob, 'ORD-BOB-2')

    response = signed_in(alice.user, workspace).patch(
        f'{RETURNS_URL}{return_request.id}/', {'order': bobs_order.id}, format='json',
    )

    assert response.status_code == 403
    return_request.refresh_from_db()
    assert return_request.order_id != bobs_order.id


def test_a_customer_cannot_write_the_shops_note(workspace, alice, alices_return):
    return_request, _, _ = alices_return

    response = signed_in(alice.user, workspace).patch(
        f'{RETURNS_URL}{return_request.id}/', {'admin_note': 'Approved'}, format='json',
    )

    assert response.status_code == 403
    return_request.refresh_from_db()
    assert return_request.admin_note == ''


def test_a_customer_edits_their_note_while_the_return_is_open(workspace, alice, alices_return):
    return_request, _, _ = alices_return

    response = signed_in(alice.user, workspace).patch(
        f'{RETURNS_URL}{return_request.id}/', {'customer_note': 'The box was crushed'}, format='json',
    )

    assert response.status_code == 200, response.data
    return_request.refresh_from_db()
    assert return_request.customer_note == 'The box was crushed'


def test_a_customer_cannot_edit_a_return_the_shop_has_reviewed(workspace, alice, alices_return):
    return_request, _, _ = alices_return
    Return.objects.filter(pk=return_request.pk).update(status='approved')

    response = signed_in(alice.user, workspace).patch(
        f'{RETURNS_URL}{return_request.id}/', {'customer_note': 'One more thing'}, format='json',
    )

    assert response.status_code == 400
    return_request.refresh_from_db()
    assert return_request.customer_note == ''


def test_a_customer_cannot_delete_a_return(workspace, alice, alices_return):
    return_request, _, _ = alices_return

    response = signed_in(alice.user, workspace).delete(f'{RETURNS_URL}{return_request.id}/')

    assert response.status_code == 403
    assert Return.objects.filter(pk=return_request.pk).exists()


def test_a_customer_opening_a_return_cannot_fill_in_the_shops_fields(workspace, store, alice):
    order, _ = make_order(workspace, store, alice, 'ORD-ALICE-3')

    response = signed_in(alice.user, workspace).post(
        RETURNS_URL,
        {'order': order.id, 'customer_note': 'Arrived faulty', 'status': 'refunded',
         'admin_note': 'Approved', 'closed_at': '2026-09-13T00:00:00Z'},
        format='json',
    )

    assert response.status_code == 201, response.data
    created = Return.objects.get(pk=response.data['id'])
    assert (created.status, created.admin_note, created.closed_at, created.customer_note) == (
        'open', '', None, 'Arrived faulty',
    )


def test_staff_still_run_the_return(workspace, staff_client, alices_return):
    return_request, _, _ = alices_return

    response = staff_client.patch(
        f'{RETURNS_URL}{return_request.id}/', {'status': 'received', 'admin_note': 'Collected'}, format='json',
    )

    assert response.status_code == 200, response.data
    return_request.refresh_from_db()
    assert (return_request.status, return_request.admin_note) == ('received', 'Collected')


def test_staff_cannot_move_a_return_onto_another_workspaces_order(other_workspace, staff_client, alices_return):
    return_request, _, _ = alices_return
    foreign_order, _, _ = foreign_return(other_workspace, 'foreigner-2', 'ORD-FOREIGN-2')

    response = staff_client.patch(
        f'{RETURNS_URL}{return_request.id}/', {'order': foreign_order.id}, format='json',
    )

    assert response.status_code == 400
    return_request.refresh_from_db()
    assert return_request.order_id != foreign_order.id

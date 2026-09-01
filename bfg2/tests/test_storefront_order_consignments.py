"""The courier numbers an order's own page shows.

The mini-program's order detail renders a copyable row per consignment, next to
the pickup code and the order number -- the three things a shopper is ever asked
to quote. The storefront order serializer did not send them, so that section was
dead: no rows, no explanation, and nothing in the payload to suggest why.

Only numbers the carrier has actually issued are shown. A consignment without
one has been booked but not yet numbered, and its ``consignment_number`` is our
own booking reference; handing that over as something to "track" sends the
shopper to a courier site that has never heard of it.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Address, Customer, User, Workspace
from bfg.delivery.models import Carrier, Consignment, FreightService, FreightState, FreightStatus
from bfg.shop.models import Order, Store

ORDERS_URL = '/api/v1/store/orders/'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Courier WS', slug='courier-ws', is_active=True)


@pytest.fixture
def shopper(workspace):
    user = User.objects.create_user(username='courier-shopper', email='courier@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client, customer


@pytest.fixture
def address(workspace):
    return Address.objects.create(
        workspace=workspace, full_name='Jacky Chen', phone='0211234567',
        address_line1='3 Oracle Drive', city='Auckland', country='NZ',
    )


@pytest.fixture
def order(workspace, shopper):
    _, customer = shopper
    store = Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)
    return Order.objects.create(
        workspace=workspace, store=store, customer=customer,
        order_number='ORD-COURIER-0001', subtotal=Decimal('20.00'), total=Decimal('20.00'),
    )


@pytest.fixture
def service(workspace):
    carrier = Carrier.objects.create(workspace=workspace, name='NZ Post', code='NZPOST')
    return FreightService.objects.create(
        workspace=workspace, carrier=carrier, name='Standard', code='STD',
        base_price=Decimal('5.00'), price_per_kg=Decimal('1.00'),
    )


def make_consignment(workspace, order, service, address, number, tracking):
    status = FreightStatus.objects.create(
        workspace=workspace, code=f'in-transit-{number}', name='In transit', type='consignment',
    )
    consignment = Consignment.objects.create(
        workspace=workspace, consignment_number=number, tracking_number=tracking,
        service=service, sender_address=address, recipient_address=address,
        state=FreightState.SHIPPED.value, status=status,
    )
    consignment.orders.add(order)
    return consignment


def detail(client, order):
    response = client.get(f'{ORDERS_URL}{order.id}/')
    assert response.status_code == 200, response.data
    return response.data


def test_an_order_that_has_shipped_nothing_still_has_the_key(shopper, order):
    client, _ = shopper

    # Not None, and not absent: the page renders a list, and an absent key is
    # indistinguishable from "this server does not do courier numbers".
    assert detail(client, order)['consignments'] == []


def test_a_tracked_consignment_comes_back_with_its_carrier(workspace, shopper, order, service, address):
    client, _ = shopper
    make_consignment(workspace, order, service, address, 'CN-0001', 'NZ123456789')

    consignments = detail(client, order)['consignments']

    assert [c['tracking_number'] for c in consignments] == ['NZ123456789']
    # The carrier's name travels with the number -- "NZ123456789" alone does not
    # tell a shopper whose website to type it into.
    assert consignments[0]['carrier_name'] == 'NZ Post'


def test_a_consignment_without_a_number_is_not_offered(workspace, shopper, order, service, address):
    client, _ = shopper
    make_consignment(workspace, order, service, address, 'CN-0002', '')

    assert detail(client, order)['consignments'] == []


def test_several_parcels_come_back_in_the_order_they_were_created(workspace, shopper, order, service, address):
    client, _ = shopper
    make_consignment(workspace, order, service, address, 'CN-0003', 'FIRST')
    make_consignment(workspace, order, service, address, 'CN-0004', 'SECOND')

    numbers = [c['tracking_number'] for c in detail(client, order)['consignments']]

    assert numbers == ['FIRST', 'SECOND']


def test_another_order_s_consignment_is_not_borrowed(workspace, shopper, order, service, address):
    client, customer = shopper
    other = Order.objects.create(
        workspace=workspace, store=order.store, customer=customer,
        order_number='ORD-COURIER-0002', subtotal=Decimal('5.00'), total=Decimal('5.00'),
    )
    make_consignment(workspace, other, service, address, 'CN-0005', 'NOT-OURS')

    assert detail(client, order)['consignments'] == []


def test_the_list_endpoint_carries_them_too(workspace, shopper, order, service, address):
    client, _ = shopper
    make_consignment(workspace, order, service, address, 'CN-0006', 'NZ987654321')

    body = client.get(ORDERS_URL).json()
    rows = body['results'] if isinstance(body, dict) else body
    row = next(r for r in rows if r['id'] == order.id)

    assert [c['tracking_number'] for c in row['consignments']] == ['NZ987654321']

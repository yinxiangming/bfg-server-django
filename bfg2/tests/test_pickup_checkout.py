"""The storefront half of collection: what the checkout picker can see and price.

Both endpoints are reachable before there is an account — a shopper has to see
the options and their prices while deciding, which is exactly when they are
still anonymous.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Workspace
from bfg.delivery.models import PickupPoint
from bfg.shop.models import Product

POINTS_URL = '/api/v1/delivery/pickup-points/for_storefront/'
PREVIEW_URL = '/api/v1/store/cart/preview/'
CART_URL = '/api/v1/store/cart/'
GUEST_KEY = 'pickup-key-2f9a1c04-7b3d-4e18-a0c6-51d8e7b39a42'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Pickup WS', slug='pickup-ws', is_active=True)


@pytest.fixture
def client(workspace):
    c = APIClient()
    c.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=GUEST_KEY,
    )
    return c


def fill_cart(client, workspace):
    """A cart with something in it — an empty one short-circuits every total."""
    product = Product.objects.create(
        workspace=workspace, name='Bag of Rice', slug='bag-of-rice',
        price=Decimal('20.00'), is_active=True, track_inventory=False,
    )
    response = client.post(f'{CART_URL}add_item/', {'product': product.id, 'quantity': 1}, format='json')
    assert response.status_code == 200, response.data


def make_point(workspace, code, **kwargs):
    return PickupPoint.all_objects.create(
        workspace=workspace,
        name=kwargs.pop('name', code.title()),
        code=code,
        address_line1=kwargs.pop('address_line1', '3 Oracle Drive'),
        city=kwargs.pop('city', 'Auckland'),
        **kwargs,
    )


def test_only_active_points_are_offered(client, workspace):
    make_point(workspace, 'open')
    make_point(workspace, 'closed', is_active=False)

    body = client.get(POINTS_URL).json()

    assert [p['code'] for p in body] == ['open']


def test_default_point_comes_first(client, workspace):
    make_point(workspace, 'other', sort_order=1)
    make_point(workspace, 'usual', sort_order=99, is_default=True)

    body = client.get(POINTS_URL).json()

    # `is_default` outranks sort_order: it is the one the order falls back to,
    # so it is the one to offer first.
    assert [p['code'] for p in body] == ['usual', 'other']


def test_the_payload_carries_what_the_picker_renders(client, workspace):
    make_point(
        workspace, 'albany', name='Albany', address_line2='Albany',
        state='Auckland', postal_code='0632', country='NZ',
        phone='021703353', instructions='Sat 2-6pm, side door',
        latitude=Decimal('-36.7324013'), longitude=Decimal('174.7123474'),
        fee=Decimal('2.50'),
    )

    point = client.get(POINTS_URL).json()[0]

    assert point['address'] == '3 Oracle Drive, Albany, Auckland, 0632, NZ'
    assert point['instructions'] == 'Sat 2-6pm, side door'
    assert point['fee'] == '2.50'
    # Nothing internal leaks to an anonymous caller.
    assert 'email' not in point and 'warehouse' not in point


def test_full_address_does_not_repeat_a_city_that_is_its_own_region(workspace):
    point = make_point(workspace, 'akl', state='Auckland', city='Auckland', postal_code='0632')

    assert point.full_address == '3 Oracle Drive, Auckland, 0632'


def test_preview_prices_collection_at_the_points_fee(client, workspace):
    fill_cart(client, workspace)
    make_point(workspace, 'albany', is_default=True, fee=Decimal('2.50'))

    pickup = client.get(PREVIEW_URL, {'fulfillment_method': 'pickup'}).json()

    # No point named, so it falls back to the default -- same rule as checkout.
    assert pickup['shipping_cost'] == '2.50'
    assert pickup['total'] == '22.50'


def test_preview_charges_the_named_point_not_the_default(client, workspace):
    fill_cart(client, workspace)
    make_point(workspace, 'usual', is_default=True, fee=Decimal('2.50'))
    other = make_point(workspace, 'other', fee=Decimal('5.00'))

    body = client.get(PREVIEW_URL, {'fulfillment_method': 'pickup', 'pickup_point': other.id}).json()

    assert body['shipping_cost'] == '5.00'


def test_preview_does_not_refuse_a_shopper_who_has_not_chosen_yet(client, workspace):
    # No points configured at all. Checkout is entitled to 400 here; a preview is
    # not, because the shopper is still looking at the options.
    fill_cart(client, workspace)

    body = client.get(PREVIEW_URL, {'fulfillment_method': 'pickup'}).json()

    assert body['shipping_cost'] == '0.00'


# ---------------------------------------------------------------------------
# Placing the order
# ---------------------------------------------------------------------------

CHECKOUT_URL = f'{CART_URL}checkout/'
GUEST_CHECKOUT_URL = f'{CART_URL}guest_checkout/'


@pytest.fixture
def store(workspace):
    from bfg.shop.models import Store
    return Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)


def test_collecting_needs_no_delivery_address(client, workspace, store):
    """The regression this whole feature exists to remove.

    Checkout used to refuse any order without a shipping address, so a shop
    whose customers collect had to invent one for every order.
    """
    from bfg.common.models import User
    from bfg.shop.models import Order

    user = User.objects.create(username='collector', email='collector@example.com', is_active=True)
    client.force_authenticate(user=user)
    fill_cart(client, workspace)
    point = make_point(workspace, 'albany', is_default=True, fee=Decimal('2.50'))

    response = client.post(
        CHECKOUT_URL,
        {'store': store.id, 'fulfillment_method': 'pickup'},
        format='json',
    )

    assert response.status_code == 201, response.data
    order = Order.all_objects.get(id=response.data['id'])
    assert order.fulfillment_method == 'pickup'
    assert order.pickup_point_id == point.id
    assert order.shipping_address_id is None
    assert order.shipping_cost == Decimal('2.50')


def test_shipping_still_demands_an_address(client, workspace, store):
    from bfg.common.models import User

    user = User.objects.create(username='poster', email='poster@example.com', is_active=True)
    client.force_authenticate(user=user)
    fill_cart(client, workspace)

    response = client.post(CHECKOUT_URL, {'store': store.id}, format='json')

    assert response.status_code == 400


def test_collecting_without_any_point_configured_is_refused(client, workspace, store):
    # No point and no default: the order would be uncollectable, so checkout
    # says so rather than recording a place nobody can go to.
    from bfg.common.models import User

    user = User.objects.create(username='nowhere', email='nowhere@example.com', is_active=True)
    client.force_authenticate(user=user)
    fill_cart(client, workspace)

    response = client.post(
        CHECKOUT_URL, {'store': store.id, 'fulfillment_method': 'pickup'}, format='json'
    )

    assert response.status_code == 400
    assert 'pickup_point' in response.data


def test_a_guest_can_collect_too(client, workspace, store):
    from bfg.shop.models import Order

    fill_cart(client, workspace)
    point = make_point(workspace, 'albany', is_default=True)

    response = client.post(
        GUEST_CHECKOUT_URL,
        {
            'store': store.id,
            'fulfillment_method': 'pickup',
            # Name, email and phone still matter: that is how the shop says
            # "ready". The street address does not.
            'email': 'walkin@example.com',
            'full_name': 'Walk In',
            'phone': '0211234567',
        },
        format='json',
    )

    assert response.status_code == 201, response.data
    order = Order.all_objects.get(id=response.data['id'])
    assert order.pickup_point_id == point.id
    assert order.shipping_address_id is None


# ---------------------------------------------------------------------------
# ready_for_pickup
# ---------------------------------------------------------------------------

def test_ready_for_pickup_stamps_the_time_without_claiming_a_parcel_moved(workspace, store):
    """`order.shipped` tells the customer a parcel is on its way. Nothing is."""
    from bfg.common.models import Customer, User
    from bfg.shop.models import Order
    from bfg.shop.services import OrderService

    user = User.objects.create(username='ready', email='ready@example.com', is_active=True)
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    order = Order.objects.create(
        workspace=workspace, customer=customer, store=store, order_number='ORD-READY-1',
        fulfillment_method='pickup', subtotal=Decimal('10'), total=Decimal('10'),
    )

    events = []
    service = OrderService(workspace=workspace, user=user)
    service.emit_event = lambda name, data: events.append(name)

    service.update_order_status(order, 'ready_for_pickup')

    order.refresh_from_db()
    assert order.status == 'ready_for_pickup'
    assert order.shipped_at is not None      # the moment it stopped waiting on us
    assert events == ['order.ready_for_pickup']

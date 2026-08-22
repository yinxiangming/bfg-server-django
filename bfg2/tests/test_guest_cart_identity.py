"""
Guest cart identity via the X-Bfg-Cart-Session header.

The storefront and the API are served from different registrable domains
(geeker.co.nz vs api.surlex.co.nz), which makes Django's ``sessionid`` a
cross-site cookie. SameSite=Lax stops the browser sending it on a ``fetch()``,
so without a header the API greets every request as a new visitor and hands it
a brand-new empty cart.

That produced a cart page listing its items at $5.00 while Order Summary
totalled $0.00: the items came from the add-to-cart response held in the
client, whereas ``/cart/preview/`` ran against a different, empty cart. The
client now carries its own opaque key and sends it on every storefront call.

These tests deliberately use a fresh ``APIClient`` per request. Django's test
client keeps cookies between calls, which would paper over the very failure
mode being pinned down here — only the header may carry identity.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Workspace, User, Customer
from bfg.shop.models import Product, Cart

CART_URL = '/api/v1/store/cart/'
GUEST_KEY = 'guest-key-6f1c0a3e-1d4b-4f2a-9c77-0b2e5a8d3c19'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Guest Cart WS', slug='guest-cart-ws', is_active=True)


@pytest.fixture
def product(workspace):
    return Product.objects.create(
        workspace=workspace,
        name='Round Wearable Microcontroller Board',
        slug='round-wearable-microcontroller-board',
        price=Decimal('5.00'),
        is_active=True,
        track_inventory=False,
    )


def guest(workspace, key=GUEST_KEY):
    """A cookie-less client that identifies itself only by the header."""
    client = APIClient()
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=key,
    )
    return client


def add_item(workspace, product, key=GUEST_KEY, quantity=1):
    response = guest(workspace, key).post(
        f'{CART_URL}add_item/',
        {'product': product.id, 'quantity': quantity},
        format='json',
    )
    assert response.status_code == 200, response.data
    return response


def test_preview_totals_match_the_items_added_under_the_same_key(workspace, product):
    """The $0.00 Order Summary regression."""
    add_item(workspace, product)

    response = guest(workspace).get(f'{CART_URL}preview/')

    assert response.status_code == 200, response.data
    assert response.data['subtotal'] == '5.00'


def test_cart_contents_survive_across_requests_without_a_cookie(workspace, product):
    add_item(workspace, product)

    response = guest(workspace).get(f'{CART_URL}current/')

    assert response.status_code == 200, response.data
    assert [(item['name'], item['quantity']) for item in response.data['items']] == [
        (product.name, 1)
    ]


def test_each_key_gets_its_own_cart(workspace, product):
    """The key is a bearer credential: it must not be a shared workspace cart."""
    add_item(workspace, product)

    response = guest(workspace, key='a-different-guest-key').get(f'{CART_URL}preview/')

    assert response.status_code == 200, response.data
    assert response.data['subtotal'] == '0.00'


def test_guest_cart_merges_into_the_customer_cart_on_sign_in(workspace, product):
    """Items added before signing in must follow the visitor into their account."""
    add_item(workspace, product)
    user = User.objects.create_user(username='shopper', email='shopper@test.com', password='x')

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=GUEST_KEY,
    )
    response = client.get(f'{CART_URL}current/')

    assert response.status_code == 200, response.data
    assert [(item['name'], item['quantity']) for item in response.data['items']] == [
        (product.name, 1)
    ]
    # all_objects: the tenant-scoped default manager filters on a thread-local
    # workspace that conftest clears between tests.
    customer = Customer.all_objects.get(workspace=workspace, user=user)
    assert Cart.all_objects.get(id=response.data['id']).customer == customer


def test_merging_the_same_key_twice_does_not_double_the_quantity(workspace, product):
    """The client keeps sending the key after sign-in; the merge must be idempotent."""
    add_item(workspace, product)
    user = User.objects.create_user(username='shopper2', email='shopper2@test.com', password='x')

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=GUEST_KEY,
    )
    client.get(f'{CART_URL}current/')
    response = client.get(f'{CART_URL}current/')

    assert [item['quantity'] for item in response.data['items']] == [1]

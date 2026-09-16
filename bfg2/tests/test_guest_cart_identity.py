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
from bfg.shop.models import Product, Cart, Store

CART_URL = '/api/v1/store/cart/'


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


def guest(workspace, token):
    """A cookie-less client that identifies itself only by a signed token."""
    client = APIClient()
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=token,
    )
    return client


def new_guest_token(workspace):
    client = APIClient()
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    response = client.get(f'{CART_URL}current/')
    assert response.status_code == 200, response.data
    return response.data['cart_token']


def add_item(workspace, product, token=None, quantity=1):
    token = token or new_guest_token(workspace)
    response = guest(workspace, token).post(
        f'{CART_URL}add_item/',
        {'product': product.id, 'quantity': quantity},
        format='json',
    )
    assert response.status_code == 200, response.data
    return response, token


def test_preview_totals_match_the_items_added_under_the_same_key(workspace, product):
    """The $0.00 Order Summary regression."""
    _, token = add_item(workspace, product)

    response = guest(workspace, token).get(f'{CART_URL}preview/')

    assert response.status_code == 200, response.data
    assert response.data['subtotal'] == '5.00'


def test_cart_contents_survive_across_requests_without_a_cookie(workspace, product):
    _, token = add_item(workspace, product)

    response = guest(workspace, token).get(f'{CART_URL}current/')

    assert response.status_code == 200, response.data
    assert [(item['name'], item['quantity']) for item in response.data['items']] == [
        (product.name, 1)
    ]


def test_each_key_gets_its_own_cart(workspace, product):
    """The key is a bearer credential: it must not be a shared workspace cart."""
    add_item(workspace, product)
    other_token = new_guest_token(workspace)

    response = guest(workspace, other_token).get(f'{CART_URL}preview/')

    assert response.status_code == 200, response.data
    assert response.data['subtotal'] == '0.00'


def test_guest_cart_merges_into_the_customer_cart_on_sign_in(workspace, product):
    """Items added before signing in must follow the visitor into their account."""
    _, token = add_item(workspace, product)
    user = User.objects.create_user(username='shopper', email='shopper@test.com', password='x')

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=token,
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
    _, token = add_item(workspace, product)
    user = User.objects.create_user(username='shopper2', email='shopper2@test.com', password='x')

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=token,
    )
    client.get(f'{CART_URL}current/')
    response = client.get(f'{CART_URL}current/')

    assert [item['quantity'] for item in response.data['items']] == [1]


def test_guest_checkout_cannot_attach_order_to_an_existing_email(workspace, product):
    """Knowing an account email is not proof that the guest owns that account."""
    _, token = add_item(workspace, product)
    victim = User.objects.create_user(
        username='existing-victim',
        email='victim@example.test',
        password='secret',
    )
    store = Store.objects.create(workspace=workspace, name='Main', code='main')

    response = guest(workspace, token).post(
        f'{CART_URL}guest_checkout/',
        {
            'store': store.id,
            'email': victim.email,
            'full_name': 'Impersonated Victim',
            'phone': '0210000000',
            'shipping_address': {
                'address_line1': '1 Queen Street',
                'city': 'Auckland',
                'country': 'NZ',
            },
        },
        format='json',
    )

    assert response.status_code == 409
    assert not Customer.all_objects.filter(workspace=workspace, user=victim).exists()

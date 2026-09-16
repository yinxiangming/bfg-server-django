"""
Paying at the counter on collection, from the admin dropdown to the checkout page.

A shop that only takes money face to face had no way to say so: `bank_transfer` asks
the customer to pay before collecting, and a `custom` gateway with a note in it cannot
express *when* it applies. This one only applies to an order the customer physically
comes and collects, which is the whole point of `supported_fulfillment_methods` — and
the restriction has to be enforced on the server, because the storefront's picker is a
hint, not a gate.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Customer, User, Workspace
from bfg.delivery.models import PickupPoint
from bfg.finance.gateways.loader import (
    GatewayLoader,
    gateway_supports_client,
    gateway_supports_fulfillment_method,
)
from bfg.finance.gateways.pay_in_store.plugin import PayInStoreGateway
from bfg.finance.models import Currency, PaymentGateway
from bfg.shop.models import Order, Store

GATEWAYS_URL = '/api/v1/store/payments/gateways/'
INTENT_URL = '/api/v1/store/payments/intent/'

DETAILS = {
    'accepted_methods': 'Cash, EFTPOS',
    'instructions': 'Pay at the counter when you collect. Bring your order number.',
}


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Counter WS', slug='counter-ws', is_active=True)


@pytest.fixture
def gateway(workspace):
    return PaymentGateway.objects.create(
        workspace=workspace,
        name='Pay in Store',
        gateway_type='pay_in_store',
        config=DETAILS,
        is_active=True,
        is_test_mode=False,
    )


def storefront(workspace):
    client = APIClient()
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


# ------------------------------------------------------- plugin discovery


def test_the_admin_dropdown_can_offer_pay_in_store():
    """The dropdown lists discovered plugins, so being discoverable is what makes it selectable."""
    assert GatewayLoader.get_plugin_class('pay_in_store') is PayInStoreGateway


def test_the_type_survives_the_admin_form(workspace):
    """
    The dropdown is built from plugins but the write goes through a ModelSerializer,
    which validates against the model's choices — a plugin the model has never heard of
    is offered and then rejected on save.
    """
    from bfg.finance.serializers import PaymentGatewaySerializer

    serializer = PaymentGatewaySerializer(data={
        'name': 'Pay in Store', 'gateway_type': 'pay_in_store', 'config': DETAILS,
    })
    assert serializer.is_valid(), serializer.errors


def test_the_admin_gets_a_form_for_the_counter_details():
    info = GatewayLoader.get_plugin_info('pay_in_store')

    assert info['display_name'] == 'Pay in Store'
    assert set(info['config_schema']) == set(PayInStoreGateway.DISPLAY_FIELDS)


def test_nothing_in_the_config_is_a_secret():
    """It is all written to be read by the customer."""
    schema = GatewayLoader.get_plugin_info('pay_in_store')['config_schema']
    assert not [f for f, spec in schema.items() if spec.get('sensitive')]


def test_every_client_can_use_it():
    """Nothing here needs an SDK, so it is not restricted the way a card gateway is."""
    for client in ('web', 'android', 'ios', 'mp'):
        assert gateway_supports_client('pay_in_store', client) is True


def test_only_a_collected_order_can_be_paid_at_the_counter():
    assert gateway_supports_fulfillment_method('pay_in_store', 'pickup') is True
    assert gateway_supports_fulfillment_method('pay_in_store', 'shipping') is False


def test_a_gateway_that_declares_no_restriction_is_unrestricted():
    """Empty means either way, and a type with no plugin at all has not opted in."""
    assert gateway_supports_fulfillment_method('bank_transfer', 'shipping') is True
    assert gateway_supports_fulfillment_method('bank_transfer', 'pickup') is True
    assert gateway_supports_fulfillment_method('paypal', 'shipping') is True


# ------------------------------------------------------- storefront listing


def test_the_checkout_is_offered_the_gateway(workspace, gateway):
    response = storefront(workspace).get(GATEWAYS_URL)

    assert response.status_code == 200
    assert [g['gateway_type'] for g in response.data] == ['pay_in_store']


def test_the_checkout_is_told_what_the_counter_takes(workspace, gateway):
    display = storefront(workspace).get(GATEWAYS_URL).data[0]['display_info']

    assert display['accepted_methods'] == 'Cash, EFTPOS'
    assert display['instructions'].startswith('Pay at the counter')


def test_the_checkout_is_told_the_restriction(workspace, gateway):
    """So the picker can hide the option the moment the shopper switches to delivery."""
    listed = storefront(workspace).get(GATEWAYS_URL).data[0]
    assert listed['supported_fulfillment_methods'] == ['pickup']


def test_a_delivery_checkout_is_not_offered_it(workspace, gateway):
    response = storefront(workspace).get(GATEWAYS_URL, {'fulfillment_method': 'shipping'})
    assert response.data == []


def test_a_collection_checkout_is_offered_it(workspace, gateway):
    response = storefront(workspace).get(GATEWAYS_URL, {'fulfillment_method': 'pickup'})
    assert [g['gateway_type'] for g in response.data] == ['pay_in_store']


def test_the_filter_leaves_the_unrestricted_gateways_alone(workspace, gateway):
    """
    The regression this guards: filtering by fulfillment must not empty a checkout that
    pays by transfer, which works either way.
    """
    PaymentGateway.objects.create(
        workspace=workspace, name='Bank Transfer', gateway_type='bank_transfer',
        config={'account_name': 'X', 'account_number': '1'}, is_active=True,
    )
    response = storefront(workspace).get(GATEWAYS_URL, {'fulfillment_method': 'shipping'})

    assert [g['gateway_type'] for g in response.data] == ['bank_transfer']


def test_optional_fields_come_back_as_empty_strings_not_missing_keys(workspace):
    """The client reads every field; a missing key would render 'undefined'."""
    PaymentGateway.objects.create(
        workspace=workspace, name='Pay in Store', gateway_type='pay_in_store',
        config={}, is_active=True,
    )
    display = storefront(workspace).get(GATEWAYS_URL).data[0]['display_info']

    assert display == {f: '' for f in PayInStoreGateway.DISPLAY_FIELDS}


def test_an_inactive_gateway_is_not_offered(workspace, gateway):
    gateway.is_active = False
    gateway.save(update_fields=['is_active'])
    assert storefront(workspace).get(GATEWAYS_URL).data == []


def test_another_workspaces_gateway_is_not_offered(workspace, gateway, db):
    other = Workspace.objects.create(name='Other', slug='other-counter-ws', is_active=True)
    assert storefront(other).get(GATEWAYS_URL).data == []


# ------------------------------------------------------- the restriction, enforced


@pytest.fixture
def currency(db):
    return Currency.objects.create(code='USD', name='US Dollar', symbol='$', is_active=True)


@pytest.fixture
def shopper(workspace):
    user = User.objects.create_user(username='counter-shopper', email='counter@test.com', password='x')
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client, customer


@pytest.fixture
def store(workspace):
    return Store.objects.create(workspace=workspace, name='Main', code='main', is_active=True)


@pytest.fixture
def point(workspace):
    return PickupPoint.all_objects.create(
        workspace=workspace, name='Albany', code='albany',
        address_line1='3 Oracle Drive', city='Auckland', is_active=True, is_default=True,
    )


def make_order(workspace, customer, store, number, **kwargs):
    return Order.objects.create(
        workspace=workspace, customer=customer, store=store, order_number=number,
        subtotal=Decimal('20.00'), total=Decimal('20.00'), **kwargs,
    )


def test_a_posted_order_cannot_pay_at_the_counter(workspace, gateway, shopper, store, currency):
    """
    The picker is display only. Without this check a client that never sent
    ``fulfillment_method`` — or simply posted the gateway id — would attach a
    pay-at-the-counter payment to an order nobody ever comes to collect.
    """
    client, customer = shopper
    order = make_order(workspace, customer, store, 'ORD-SHIP-1', fulfillment_method='shipping')

    response = client.post(
        INTENT_URL, {'order_id': order.id, 'gateway_id': gateway.id}, format='json'
    )

    assert response.status_code == 400
    assert response.data['code'] == 'gateway_fulfillment_mismatch'


def test_a_collected_order_can_pay_at_the_counter(workspace, gateway, shopper, store, point, currency):
    client, customer = shopper
    order = make_order(
        workspace, customer, store, 'ORD-PICK-1',
        fulfillment_method='pickup', pickup_point=point,
    )

    response = client.post(
        INTENT_URL, {'order_id': order.id, 'gateway_id': gateway.id}, format='json'
    )

    assert response.status_code == 201, response.data
    # Nothing is charged online: the payment waits for the customer to turn up.
    assert response.data['status'] == 'pending'


# ------------------------------------------------------- payment flow


def test_nothing_is_charged_online(workspace, gateway):
    """
    The money changes hands at the counter, so the gateway only records that the shop
    is waiting. Staff mark it received via `payments/{id}/process/`.
    """
    plugin = GatewayLoader.get_plugin(gateway)

    intent = plugin.create_payment_intent(customer=None, amount=None, currency=None)
    assert intent['status'] == 'pending'

    confirmed = plugin.confirm_payment(payment=None)
    assert confirmed['success'] is True
    assert confirmed['status'] == 'pending'


def test_it_refuses_to_pretend_it_can_save_an_instrument(workspace, gateway):
    """Cash over a counter is not something the shop can keep on file."""
    plugin = GatewayLoader.get_plugin(gateway)
    with pytest.raises(NotImplementedError):
        plugin.save_payment_method(customer=None, gateway_payment_method_id='x')

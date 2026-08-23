"""
The bank transfer gateway, end to end from the admin dropdown to the checkout page.

`bank_transfer` sat in `PaymentGateway.GATEWAY_TYPE_CHOICES` and in the storefront
serializer's display fallback, but no plugin implemented it — and the admin's gateway
dropdown is built from *discovered plugins*, not from the model's choices. So the type
was unreachable, and a shop with no card processor had no way to accept money: the
checkout rendered "no payment methods are currently available" and no order could be
completed.
"""

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Workspace
from bfg.finance.gateways.bank_transfer.plugin import BankTransferGateway
from bfg.finance.gateways.loader import GatewayLoader, gateway_supports_client
from bfg.finance.models import PaymentGateway

GATEWAYS_URL = '/api/v1/store/payments/gateways/'

DETAILS = {
    'bank_name': 'Example Bank',
    'account_name': 'Example Trading Ltd',
    'account_number': '00-0000-0000000-00',
    'instructions': 'Use your order number as the reference. Ships once payment clears.',
}


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Bank WS', slug='bank-ws', is_active=True)


@pytest.fixture
def gateway(workspace):
    return PaymentGateway.objects.create(
        workspace=workspace,
        name='Bank Transfer',
        gateway_type='bank_transfer',
        config=DETAILS,
        is_active=True,
        is_test_mode=False,
    )


def storefront(workspace):
    client = APIClient()
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


# ------------------------------------------------------- plugin discovery


def test_the_admin_dropdown_can_offer_bank_transfer():
    """The dropdown lists discovered plugins, so being discoverable is what makes it selectable."""
    assert GatewayLoader.get_plugin_class('bank_transfer') is BankTransferGateway


def test_the_admin_gets_a_form_for_the_bank_details():
    info = GatewayLoader.get_plugin_info('bank_transfer')

    assert info['display_name'] == 'Bank Transfer'
    schema = info['config_schema']
    assert set(schema) == set(BankTransferGateway.DISPLAY_FIELDS)
    assert [f for f, spec in schema.items() if spec['required']] == ['account_name', 'account_number']


def test_no_bank_detail_is_hidden_from_the_admin_as_a_secret():
    """They are the merchant's own details and the customer has to read them to pay."""
    schema = GatewayLoader.get_plugin_info('bank_transfer')['config_schema']
    assert not [f for f, spec in schema.items() if spec.get('sensitive')]


def test_every_client_can_use_it():
    """Nothing here needs an SDK, so it is not restricted the way a card gateway is."""
    for client in ('web', 'android', 'ios', 'mp'):
        assert gateway_supports_client('bank_transfer', client) is True


# ------------------------------------------------------- storefront


def test_the_checkout_is_offered_the_gateway(workspace, gateway):
    response = storefront(workspace).get(GATEWAYS_URL)

    assert response.status_code == 200
    assert [g['gateway_type'] for g in response.data] == ['bank_transfer']


def test_the_checkout_is_given_the_account_details(workspace, gateway):
    """
    The client decides a gateway is 'place the order and show instructions' by finding
    these fields in display_info; without them it would fall through to the card flow.
    """
    response = storefront(workspace).get(GATEWAYS_URL)
    display = response.data[0]['display_info']

    assert display['bank_name'] == 'Example Bank'
    assert display['account_name'] == 'Example Trading Ltd'
    assert display['account_number'] == '00-0000-0000000-00'
    assert display['instructions'].startswith('Use your order number')


def test_optional_fields_come_back_as_empty_strings_not_missing_keys(workspace, gateway):
    """The client reads every field; a missing key would render 'undefined'."""
    display = storefront(workspace).get(GATEWAYS_URL).data[0]['display_info']
    assert display['routing_number'] == ''
    assert display['swift_code'] == ''


def test_a_half_configured_gateway_does_not_break_the_listing(workspace):
    """
    Required-ness is enforced by the admin form, so an incomplete gateway can still
    reach the database. It must degrade to blanks rather than take down checkout.
    """
    PaymentGateway.objects.create(
        workspace=workspace, name='Bank Transfer', gateway_type='bank_transfer',
        config={}, is_active=True,
    )
    response = storefront(workspace).get(GATEWAYS_URL)

    assert response.status_code == 200
    assert response.data[0]['display_info'] == {f: '' for f in BankTransferGateway.DISPLAY_FIELDS}


def test_test_mode_reads_the_test_config(workspace):
    gateway = PaymentGateway.objects.create(
        workspace=workspace, name='Bank Transfer', gateway_type='bank_transfer',
        config=DETAILS, test_config={**DETAILS, 'account_number': '99-9999-9999999-99'},
        is_active=True, is_test_mode=True,
    )
    display = storefront(workspace).get(GATEWAYS_URL).data[0]['display_info']
    assert display['account_number'] == '99-9999-9999999-99'


def test_an_inactive_gateway_is_not_offered(workspace, gateway):
    gateway.is_active = False
    gateway.save(update_fields=['is_active'])
    assert storefront(workspace).get(GATEWAYS_URL).data == []


def test_another_workspaces_bank_details_are_not_exposed(workspace, gateway, db):
    other = Workspace.objects.create(name='Other', slug='other-bank-ws', is_active=True)
    assert storefront(other).get(GATEWAYS_URL).data == []


# ------------------------------------------------------- payment flow


def test_nothing_is_charged_online(workspace, gateway):
    """
    The money arrives out of band, so the gateway only records that the shop is waiting.
    An admin marks it received once it lands.
    """
    plugin = GatewayLoader.get_plugin(gateway)

    intent = plugin.create_payment_intent(customer=None, amount=None, currency=None)
    assert intent['status'] == 'pending'

    confirmed = plugin.confirm_payment(payment=None)
    assert confirmed['success'] is True
    assert confirmed['status'] == 'pending'


def test_it_refuses_to_pretend_it_can_save_an_instrument(workspace, gateway):
    """A transfer is initiated from the customer's bank; there is nothing to keep on file."""
    plugin = GatewayLoader.get_plugin(gateway)
    with pytest.raises(NotImplementedError):
        plugin.save_payment_method(customer=None, gateway_payment_method_id='x')

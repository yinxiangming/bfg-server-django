"""
Payment callbacks have to prove they came from the gateway.

`POST /api/v1/store/payments/callback/<gateway>/` takes no authentication. It checked a
signature only when the request carried one, `BasePaymentGateway.verify_webhook` accepted
anything, and `PaymentService.handle_webhook` found the payment by an id read from the
request body. So an unsigned `payment.succeeded` completed a payment and marked its order
paid. The id is easy to come by: for Stripe it is the shopper's own PaymentIntent, and every
bank transfer, pay in store and custom payment carries the same constant.

A shop sets its own webhook secret, so a signature vouches only for that shop's gateway: a
signed event must not reach a payment that belongs to another gateway.
"""

import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.middleware import set_current_workspace
from bfg.common.models import Customer, Workspace
from bfg.finance.gateways.loader import get_gateway_plugin
from bfg.finance.models import Currency, Payment, PaymentGateway

User = get_user_model()

SECRET = 'whsec_shop_a'
STRIPE_CONFIG = {'secret_key': 'sk_test_dummy', 'webhook_secret': SECRET}
BANK_DETAILS = {
    'bank_name': 'Example Bank',
    'account_name': 'Example Trading Ltd',
    'account_number': '00-0000-0000000-00',
}


@pytest.fixture(autouse=True)
def _no_workspace_leak():
    set_current_workspace(None)
    yield
    set_current_workspace(None)


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Shop A', slug='shop-a', is_active=True)


@pytest.fixture
def currency(db):
    currency, _ = Currency.objects.get_or_create(code='NZD', defaults={'name': 'NZ Dollar', 'symbol': '$'})
    return currency


def make_gateway(workspace, gateway_type, config):
    return PaymentGateway.objects.create(
        workspace=workspace, name=gateway_type, gateway_type=gateway_type,
        config=config, test_config=config, is_active=True, is_test_mode=True,
    )


def make_payment(gateway, currency, transaction_id, status='processing'):
    workspace = gateway.workspace
    shopper = User.objects.create_user(
        username=f'shopper-{workspace.slug}-{transaction_id}',
        email=f'{transaction_id}@example.com',
        password='x' * 12,
    )
    customer = Customer.all_objects.create(workspace=workspace, user=shopper)
    return Payment.all_objects.create(
        workspace=workspace, customer=customer, payment_number=f'PAY-{workspace.slug}-{transaction_id}',
        gateway=gateway, gateway_display_name=gateway.name, gateway_type=gateway.gateway_type,
        amount=Decimal('99.00'), currency=currency, status=status, gateway_transaction_id=transaction_id,
    )


def intent_id(gateway, currency):
    """The id the storefront stores on a new payment for this gateway."""
    intent = get_gateway_plugin(gateway).create_payment_intent(
        customer=None, amount=Decimal('99.00'), currency=currency,
    )
    return intent['payment_intent_id']


def event_body(event_type, object_id, metadata_workspace):
    return json.dumps({
        'id': 'evt_test', 'object': 'event', 'type': event_type,
        'data': {'object': {'id': object_id, 'metadata': {'workspace_id': metadata_workspace.id}}},
    })


def stripe_signature(body, secret=SECRET):
    timestamp = int(time.time())
    digest = hmac.new(secret.encode(), f'{timestamp}.{body}'.encode(), hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'


def post_callback(gateway_type, body, workspace, **headers):
    return APIClient().post(
        f'/api/v1/store/payments/callback/{gateway_type}/', data=body, content_type='application/json',
        HTTP_X_WORKSPACE_ID=str(workspace.id), **headers,
    )


def status_of(payment):
    return Payment.all_objects.get(pk=payment.pk).status


# ------------------------------------------------------------------ Stripe


def test_an_unsigned_event_is_refused(workspace, currency):
    payment = make_payment(make_gateway(workspace, 'stripe', STRIPE_CONFIG), currency, 'pi_unsigned')
    body = event_body('payment_intent.succeeded', 'pi_unsigned', workspace)

    res = post_callback('stripe', body, workspace)

    assert res.status_code == 401
    assert status_of(payment) == 'processing'


def test_a_forged_signature_is_refused(workspace, currency):
    payment = make_payment(make_gateway(workspace, 'stripe', STRIPE_CONFIG), currency, 'pi_forged')
    body = event_body('payment_intent.succeeded', 'pi_forged', workspace)

    res = post_callback('stripe', body, workspace, HTTP_STRIPE_SIGNATURE=stripe_signature(body, 'whsec_guess'))

    assert res.status_code == 401
    assert status_of(payment) == 'processing'


def test_a_genuine_event_completes_the_payment(workspace, currency):
    payment = make_payment(make_gateway(workspace, 'stripe', STRIPE_CONFIG), currency, 'pi_genuine')
    body = event_body('payment_intent.succeeded', 'pi_genuine', workspace)

    res = post_callback('stripe', body, workspace, HTTP_STRIPE_SIGNATURE=stripe_signature(body))

    assert res.status_code == 200, res.data
    assert status_of(payment) == 'completed'


def test_without_a_webhook_secret_a_signed_event_is_refused(workspace, currency):
    gateway = make_gateway(workspace, 'stripe', {'secret_key': 'sk_test_dummy'})
    payment = make_payment(gateway, currency, 'pi_nosecret')
    body = event_body('payment_intent.succeeded', 'pi_nosecret', workspace)

    res = post_callback('stripe', body, workspace, HTTP_STRIPE_SIGNATURE=stripe_signature(body))

    assert res.status_code == 401
    assert status_of(payment) == 'processing'


def test_a_late_failure_does_not_undo_a_completed_payment(workspace, currency):
    payment = make_payment(make_gateway(workspace, 'stripe', STRIPE_CONFIG), currency, 'pi_done', status='completed')
    body = event_body('payment_intent.payment_failed', 'pi_done', workspace)

    res = post_callback('stripe', body, workspace, HTTP_STRIPE_SIGNATURE=stripe_signature(body))

    assert res.status_code == 200, res.data
    assert status_of(payment) == 'completed'


# ------------------------------------------------ whose signature reaches which payment


def test_a_signed_event_only_reaches_payments_of_the_gateway_that_verified_it(workspace, currency):
    make_gateway(workspace, 'stripe', STRIPE_CONFIG)
    bank = make_gateway(workspace, 'bank_transfer', BANK_DETAILS)
    bank_payment = make_payment(bank, currency, intent_id(bank, currency), status='pending')
    body = event_body('payment_intent.succeeded', bank_payment.gateway_transaction_id, workspace)

    res = post_callback('stripe', body, workspace, HTTP_STRIPE_SIGNATURE=stripe_signature(body))

    assert res.status_code == 200, res.data
    assert status_of(bank_payment) == 'pending'


def test_a_shop_cannot_sign_its_way_into_another_shops_payment(db, currency):
    shop_a = Workspace.objects.create(name='Shop A', slug='shop-a', is_active=True)
    shop_b = Workspace.objects.create(name='Shop B', slug='shop-b', is_active=True)
    make_gateway(shop_a, 'stripe', STRIPE_CONFIG)
    shop_b_gateway = make_gateway(shop_b, 'stripe', {'secret_key': 'sk_test_dummy', 'webhook_secret': 'whsec_shop_b'})
    victim = make_payment(shop_b_gateway, currency, 'pi_shop_b')
    # Signed with shop A's secret and naming shop A in the metadata, but sent to shop B.
    body = event_body('payment_intent.succeeded', 'pi_shop_b', shop_a)

    res = post_callback('stripe', body, shop_b, HTTP_STRIPE_SIGNATURE=stripe_signature(body))

    assert res.status_code == 401
    assert status_of(victim) == 'processing'


# ------------------------------------------------ gateways that receive no webhooks


@pytest.mark.parametrize('headers', [
    {},
    {'HTTP_X_GATEWAY_SIGNATURE': 'anything'},
    {'HTTP_STRIPE_SIGNATURE': 't=1,v1=anything'},
], ids=['unsigned', 'gateway-header', 'stripe-header'])
@pytest.mark.parametrize('gateway_type, config', [
    ('bank_transfer', BANK_DETAILS),
    ('pay_in_store', {}),
    ('custom', {}),
])
def test_gateways_without_webhooks_refuse_every_callback(workspace, currency, gateway_type, config, headers):
    gateway = make_gateway(workspace, gateway_type, config)
    payment = make_payment(gateway, currency, intent_id(gateway, currency), status='pending')
    body = event_body('payment.succeeded', payment.gateway_transaction_id, workspace)

    res = post_callback(gateway_type, body, workspace, **headers)

    assert res.status_code == 401
    assert status_of(payment) == 'pending'

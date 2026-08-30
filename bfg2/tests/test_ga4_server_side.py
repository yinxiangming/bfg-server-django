"""
Server-side GA4 reporting: what gets sent, and — mostly — what does not.

The failure mode this guards against is silent. Analytics is fire-and-forget by
design, so a broken payload, a missing secret or an exception in the handler all
look identical from the outside: no data, no error. The tests below pin the parts
that would otherwise only surface as a quiet gap in a GA4 report weeks later:

* an unconfigured workspace must send *nothing* — one deployment serves several
  storefronts, and reporting the wrong one's revenue into a shared property is
  worse than reporting none;
* a measurement id with no matching secret must not silently drop either, because
  that combination is a deployment gap rather than a workspace opting out;
* the `client_id` must be stable per customer and never contain the raw primary
  key, since it is handed to a third party;
* `purchase` must carry currency and value, which GA4 discards the event without;
* and the handler must swallow everything, because it runs inside order payment.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from bfg.common.models import Settings, Workspace
from bfg.core import analytics


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='GA4 WS', slug='ga4-ws', is_active=True)


def configure_ga4(workspace, measurement_id):
    settings_obj, _ = Settings.objects.get_or_create(workspace=workspace)
    custom = dict(settings_obj.custom_settings or {})
    custom['analytics'] = {'google_analytics_id': measurement_id}
    settings_obj.custom_settings = custom
    settings_obj.save(update_fields=['custom_settings'])
    return settings_obj


# ---------------------------------------------------------------------------
# client_id
# ---------------------------------------------------------------------------

def test_client_id_is_stable_and_scoped_per_workspace():
    a = analytics.client_id_for_customer(42, 4)
    assert a == analytics.client_id_for_customer(42, 4)          # repeat purchases = one user
    assert a != analytics.client_id_for_customer(42, 5)          # same person, two storefronts
    assert a != analytics.client_id_for_customer(43, 4)


def test_client_id_does_not_leak_the_customer_primary_key():
    """It goes to Google; a raw id would let the export be joined back to our DB."""
    assert '4242' not in analytics.client_id_for_customer(4242, 1)


def test_client_id_is_empty_without_a_customer():
    assert analytics.client_id_for_customer(None, 1) == ''


# ---------------------------------------------------------------------------
# track() gating
# ---------------------------------------------------------------------------

def test_unconfigured_workspace_sends_nothing(workspace):
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay:
        assert analytics.track(workspace.id, '1.2', 'purchase', {}) is False
    delay.assert_not_called()


def test_measurement_id_without_a_secret_does_not_send(workspace):
    """A deployment gap, not an opt-out — it must not quietly look like success."""
    configure_ga4(workspace, 'G-TESTONLY01')
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS', {}, create=True):
        assert analytics.track(workspace.id, '1.2', 'purchase', {}) is False
    delay.assert_not_called()


def test_configured_workspace_queues_the_event(workspace):
    configure_ga4(workspace, 'G-TESTONLY01')
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS',
                      {'G-TESTONLY01': 'shh'}, create=True):
        assert analytics.track(workspace.id, '9.9', 'login', {'method': 'wechat'}, user_id=7) is True

    delay.assert_called_once()
    ws_id, payload = delay.call_args[0]
    assert ws_id == workspace.id
    assert payload['client_id'] == '9.9'
    assert payload['user_id'] == '7'
    assert payload['events'] == [{'name': 'login', 'params': {'method': 'wechat'}}]


def test_the_api_secret_is_never_queued_through_the_broker(workspace):
    """It would otherwise sit in plain text in Redis for the life of the queue."""
    configure_ga4(workspace, 'G-TESTONLY01')
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS',
                      {'G-TESTONLY01': 'super-secret'}, create=True):
        analytics.track(workspace.id, '9.9', 'login')

    assert 'super-secret' not in repr(delay.call_args)


def test_events_are_capped_at_the_protocol_limit(workspace):
    """GA4 drops the excess silently, so the cap has to be ours to be visible."""
    configure_ga4(workspace, 'G-TESTONLY01')
    events = [{'name': f'e{i}', 'params': {}} for i in range(40)]
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS',
                      {'G-TESTONLY01': 'shh'}, create=True):
        analytics.track_many(workspace.id, '9.9', events)

    _, payload = delay.call_args[0]
    assert len(payload['events']) == analytics.MAX_EVENTS_PER_REQUEST


# ---------------------------------------------------------------------------
# order.paid -> purchase
# ---------------------------------------------------------------------------

@pytest.fixture
def paid_order(workspace):
    from bfg.common.models import Customer, User
    from bfg.shop.models import Order, OrderItem, Product, Store

    user = User.objects.create(username='ga4buyer', email='ga4buyer@example.com', is_active=True)
    customer = Customer.objects.create(workspace=workspace, user=user, is_active=True)
    store = Store.objects.create(workspace=workspace, name='GA4 Store', code='ga4-main', is_active=True)
    product = Product.objects.create(workspace=workspace, name='Widget', price=Decimal('12.50'))
    order = Order.objects.create(
        workspace=workspace, customer=customer, store=store, order_number='ORD-GA4-1',
        subtotal=Decimal('25.00'), shipping_cost=Decimal('5.00'), tax=Decimal('3.75'),
        total=Decimal('33.75'),
    )
    OrderItem.objects.create(
        order=order, product=product, product_name='Widget', sku='W-1',
        quantity=2, price=Decimal('12.50'), subtotal=Decimal('25.00'),
    )
    return order


def fire_order_paid(workspace, order):
    from bfg.shop.handlers import on_order_paid_analytics

    on_order_paid_analytics({'workspace': workspace, 'data': {'order': order}})


def test_paid_order_reports_a_purchase_with_value_and_currency(workspace, paid_order):
    configure_ga4(workspace, 'G-TESTONLY01')
    Settings.objects.filter(workspace=workspace).update(default_currency='NZD')

    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS',
                      {'G-TESTONLY01': 'shh'}, create=True):
        fire_order_paid(workspace, paid_order)

    _, payload = delay.call_args[0]
    event = payload['events'][0]
    assert event['name'] == 'purchase'
    params = event['params']
    assert params['transaction_id'] == 'ORD-GA4-1'
    assert params['value'] == 33.75
    assert params['tax'] == 3.75
    assert params['shipping'] == 5.00
    assert params['currency'] == 'NZD'          # GA4 discards a purchase without it
    assert params['items'] == [{
        'item_id': 'W-1', 'item_name': 'Widget', 'item_variant': None,
        'price': 12.50, 'quantity': 2,
    }]


def test_purchase_records_the_sales_channel(workspace, paid_order):
    """Separating mini-program revenue from web revenue is the whole point."""
    from bfg.shop.models import SalesChannel

    channel = SalesChannel.objects.create(workspace=workspace, name='Mini Program', code='wechat-mp')
    paid_order.sales_channel = channel
    paid_order.save(update_fields=['sales_channel'])

    configure_ga4(workspace, 'G-TESTONLY01')
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS',
                      {'G-TESTONLY01': 'shh'}, create=True):
        fire_order_paid(workspace, paid_order)

    _, payload = delay.call_args[0]
    assert payload['events'][0]['params']['sales_channel'] == 'wechat-mp'


def test_a_channelless_order_still_reports(workspace, paid_order):
    configure_ga4(workspace, 'G-TESTONLY01')
    with patch('bfg.core.tasks.deliver_ga4_events.delay') as delay, \
         patch.object(analytics.django_settings, 'GA4_MP_API_SECRETS',
                      {'G-TESTONLY01': 'shh'}, create=True):
        fire_order_paid(workspace, paid_order)

    _, payload = delay.call_args[0]
    assert payload['events'][0]['params']['sales_channel'] == 'unknown'


def test_analytics_failure_never_breaks_order_payment(workspace, paid_order):
    """This runs inside payment handling; an analytics bug must not fail the sale."""
    configure_ga4(workspace, 'G-TESTONLY01')
    with patch('bfg.core.analytics.track', side_effect=RuntimeError('GA4 exploded')):
        fire_order_paid(workspace, paid_order)   # must not raise

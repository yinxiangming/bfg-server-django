import pytest
from django.template import Context, Template

from bfg.common.models import Settings, User, Workspace
from bfg.inbox.models import MessageTemplate
from bfg.inbox.notification_templates import (
    NOTIFICATION_CODES,
    ensure_notification_templates,
    missing_notification_templates,
)
from bfg.inbox.services.message_service import MessageService

# What each task puts in context_data; send_notification adds the customer and order objects.
TASK_CONTEXT = {
    'order_created': {'order_number': 'ORD-1', 'total': '42.50', 'subtotal': '40.00', 'shipping_cost': '2.50',
                      'tax': '0.00', 'discount': '0.00', 'created_at': '', 'status': 'pending',
                      'payment_status': 'pending'},
    'order_processing': {'order_number': 'ORD-1'},
    'order_shipped': {'order_number': 'ORD-1', 'shipped_at': '', 'tracking_number': 'TRK-9',
                      'tracking_url': 'https://track.example.test/TRK-9'},
    'order_delivered': {'order_number': 'ORD-1', 'delivered_at': ''},
    'order_cancelled': {'order_number': 'ORD-1', 'cancellation_reason': 'Out of stock'},
    'order_refunded': {'order_number': 'ORD-1', 'refund_amount': '42.50'},
    'payment_received': {'amount': '42.50', 'currency': 'NZD', 'order_number': 'ORD-1'},
    'payment_failed': {'amount': '42.50', 'currency': 'NZD', 'order_number': 'ORD-1',
                       'failure_reason': 'Card declined'},
    'booking_confirmed': {'booking_id': 7, 'slot_display': '2026-09-14 10:00-11:00'},
}


def _workspace(slug, language='en', currency='USD'):
    workspace = Workspace.objects.create(name=slug, slug=slug)
    Settings.objects.update_or_create(
        workspace=workspace, defaults={'default_language': language, 'default_currency': currency},
    )
    return workspace


@pytest.mark.django_db
def test_seeds_every_code_in_the_workspace_language_with_only_in_app_on():
    workspace = _workspace('tmpl-zh', language='zh-hans', currency='NZD')

    result = ensure_notification_templates(workspace)

    templates = MessageTemplate.objects.filter(workspace=workspace)
    assert result['created'] == list(NOTIFICATION_CODES)
    assert sorted(templates.values_list('code', flat=True)) == sorted(NOTIFICATION_CODES)
    assert set(templates.values_list('language', flat=True)) == {'zh-hans'}
    assert all(t.app_message_enabled and t.app_message_title and t.app_message_body for t in templates)
    assert not any(t.email_enabled or t.sms_enabled or t.push_enabled for t in templates)
    # The email copy is there for the shop to switch on.
    assert all(t.email_subject and t.email_body for t in templates)
    assert '合计 NZ$' in templates.get(code='order_created').app_message_body


@pytest.mark.django_db
def test_english_workspace_gets_english_copy_with_its_own_currency_symbol():
    workspace = _workspace('tmpl-en', language='en', currency='AUD')

    ensure_notification_templates(workspace)

    template = MessageTemplate.objects.get(workspace=workspace, code='order_refunded')
    assert template.language == 'en'
    assert 'A$' in template.app_message_body


@pytest.mark.django_db
def test_a_customer_left_on_the_default_language_reads_the_shop_language():
    workspace = _workspace('tmpl-lookup', language='zh-hans', currency='NZD')
    ensure_notification_templates(workspace)
    recipient_language = User._meta.get_field('language').default

    template = MessageService(workspace=workspace, user=None).get_template('order_shipped', recipient_language)

    # An English copy beside the Chinese one would have been picked here.
    assert recipient_language == 'en'
    assert template.language == 'zh-hans'


@pytest.mark.django_db
def test_codes_the_workspace_already_has_are_left_alone():
    workspace = _workspace('tmpl-own', language='zh-hans', currency='NZD')
    own = MessageTemplate.objects.create(
        workspace=workspace, code='order_created', event='order.created', name='Own',
        language='en', is_active=False, app_message_enabled=True, app_message_body='Our words',
    )

    result = ensure_notification_templates(workspace)

    assert 'order_created' not in result['created']
    assert result['existing'] == ['order_created']
    # Switched off stays off, and no zh-hans copy appears beside it.
    assert list(MessageTemplate.objects.filter(workspace=workspace, code='order_created')) == [own]
    own.refresh_from_db()
    assert (own.is_active, own.app_message_body) == (False, 'Our words')


@pytest.mark.django_db
def test_dry_run_writes_nothing_and_a_second_run_creates_nothing():
    workspace = _workspace('tmpl-idem')

    planned = ensure_notification_templates(workspace, dry_run=True)
    assert planned['created'] == list(NOTIFICATION_CODES)
    assert not MessageTemplate.objects.filter(workspace=workspace).exists()

    ensure_notification_templates(workspace)
    assert ensure_notification_templates(workspace)['created'] == []
    assert MessageTemplate.objects.filter(workspace=workspace).count() == len(NOTIFICATION_CODES)


@pytest.mark.django_db
@pytest.mark.parametrize('language', ['en', 'zh-hans'])
def test_every_template_renders_the_values_its_task_sends(language):
    assert set(TASK_CONTEXT) == set(NOTIFICATION_CODES)
    workspace = _workspace(f'tmpl-render-{language}', language=language, currency='NZD')
    ensure_notification_templates(workspace)

    for template in MessageTemplate.objects.filter(workspace=workspace):
        context = TASK_CONTEXT[template.code]
        for field in ('app_message_title', 'app_message_body', 'email_subject', 'email_body'):
            rendered = Template(getattr(template, field)).render(Context(context))
            assert '{' not in rendered and '¤' not in rendered, (template.code, field, rendered)
        body = Template(template.app_message_body).render(Context(context))
        for key in ('order_number', 'total', 'tracking_number', 'cancellation_reason', 'refund_amount',
                    'amount', 'failure_reason', 'booking_id', 'slot_display'):
            if key in context:
                assert str(context[key]) in body, (template.code, key, body)


@pytest.mark.django_db
def test_platform_rows_and_switched_off_rows_are_not_missing():
    workspace = _workspace('tmpl-missing')
    MessageTemplate.objects.create(
        workspace=None, code='order_created', event='order.created', name='Platform', language='en',
    )
    MessageTemplate.objects.create(
        workspace=workspace, code='order_shipped', event='order.shipped', name='Off', language='en',
        is_active=False,
    )

    missing = missing_notification_templates(workspace)

    assert 'order_created' not in missing  # inherited from the platform level
    assert 'order_shipped' not in missing  # the shop switched it off
    assert len(missing) == len(NOTIFICATION_CODES) - 2

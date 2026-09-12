# -*- coding: utf-8 -*-
"""
Default notification templates for a workspace.

Order, payment and booking events each send an inbox notification
(``shop.tasks``, ``finance.tasks`` and ``web.tasks`` call
``inbox.tasks.send_notification``), and every notification needs a
``MessageTemplate`` row for its code. Creating a workspace creates none, so a
new shop's customers are told nothing until someone writes them by hand.

``ensure_notification_templates`` writes them:

* **One language, the workspace's own.** ``User.language`` defaults to ``en``,
  so in a Chinese shop that also held English copies nearly every customer
  would read English. With only the workspace language present,
  ``MessageService.get_template`` falls through to it.
* **In-app only.** The email copy is written but switched off: sending email is
  each shop's decision, once it can send mail.
* **Never overwrites.** A code the workspace already has, in any language and
  even switched off, is the shop's decision and is left alone.
* **The currency symbol is written into the copy** when seeding, because orders
  carry no currency of their own. Payment templates print the payment's own
  currency code instead.

Seeding therefore bakes in the locale the workspace has at the time. Platform
provisioning seeds a new workspace in the settings defaults, before its setup
wizard picks the real language and currency, so the wizard calls
``relocalise_notification_templates`` to rewrite whatever seeding wrote that
nobody has changed since. Changing the settings any other way rewrites nothing.
"""

from typing import Any, Dict, List, Optional, Tuple

from bfg.common.models import Settings
from bfg.common.onboarding.catalog import get_currency_profile
from bfg.inbox.models import MessageTemplate

#: Every code a bfg2 task sends a notification for.
NOTIFICATION_CODES = (
    'order_created',
    'order_processing',
    'order_shipped',
    'order_delivered',
    'order_cancelled',
    'order_refunded',
    'payment_received',
    'payment_failed',
    'booking_confirmed',
)

#: Stands for the workspace currency symbol in the copy below.
CURRENCY = '¤'

# code -> (event, what its task puts in the context besides the customer)
_SPECS = {
    'order_created': ('order.created', ['order_number', 'total', 'subtotal', 'shipping_cost', 'tax',
                                        'discount', 'status', 'payment_status']),
    'order_processing': ('order.processing', ['order_number']),
    'order_shipped': ('order.shipped', ['order_number', 'shipped_at', 'tracking_number', 'tracking_url']),
    'order_delivered': ('order.delivered', ['order_number', 'delivered_at']),
    'order_cancelled': ('order.cancelled', ['order_number', 'cancellation_reason']),
    'order_refunded': ('order.refunded', ['order_number', 'refund_amount']),
    'payment_received': ('payment.completed', ['order_number', 'amount', 'currency']),
    'payment_failed': ('payment.failed', ['order_number', 'amount', 'currency', 'failure_reason']),
    'booking_confirmed': ('booking.status_changed', ['booking_id', 'slot_display']),
}

# language -> code -> (name, in-app title, in-app body, email subject, email body)
_COPY = {
    'en': {
        'order_created': (
            'Order created',
            'Order received',
            'Thanks for your order {{ order_number }}. Total: ¤{{ total }}.',
            'Order confirmation - {{ order_number }}',
            'Thanks for your order.\n\n'
            'Order number: {{ order_number }}\n'
            'Total: ¤{{ total }}\n\n'
            'We will let you know when it ships.',
        ),
        'order_processing': (
            'Order processing',
            'Order being prepared',
            'Your order {{ order_number }} is being prepared.',
            'Your order {{ order_number }} is being prepared',
            'Your order {{ order_number }} is being prepared. We will let you know when it ships.',
        ),
        'order_shipped': (
            'Order shipped',
            'Order shipped',
            'Your order {{ order_number }} is on its way.'
            '{% if tracking_number %} Tracking number: {{ tracking_number }}{% endif %}',
            'Your order {{ order_number }} has shipped',
            'Your order {{ order_number }} is on its way.\n'
            '{% if tracking_number %}\nTracking number: {{ tracking_number }}{% endif %}'
            '{% if tracking_url %}\nTrack your parcel: {{ tracking_url }}{% endif %}',
        ),
        'order_delivered': (
            'Order delivered',
            'Order delivered',
            'Your order {{ order_number }} has been delivered. Thank you for shopping with us!',
            'Your order {{ order_number }} has been delivered',
            'Your order {{ order_number }} has been delivered.\n\n'
            'Thank you for shopping with us!',
        ),
        'order_cancelled': (
            'Order cancelled',
            'Order cancelled',
            'Your order {{ order_number }} has been cancelled.'
            '{% if cancellation_reason %} Reason: {{ cancellation_reason }}{% endif %}',
            'Your order {{ order_number }} has been cancelled',
            'Your order {{ order_number }} has been cancelled.'
            '{% if cancellation_reason %}\n\nReason: {{ cancellation_reason }}{% endif %}\n\n'
            'If you have any questions, please contact us.',
        ),
        'order_refunded': (
            'Order refunded',
            'Refund processed',
            'A refund of ¤{{ refund_amount }} for order {{ order_number }} has been processed.',
            'Refund for order {{ order_number }}',
            'A refund of ¤{{ refund_amount }} for order {{ order_number }} has been processed.\n\n'
            'It can take a few business days to reach your original payment method.',
        ),
        'payment_received': (
            'Payment received',
            'Payment received',
            'We have received your payment of {{ currency }} {{ amount }}'
            '{% if order_number %} for order {{ order_number }}{% endif %}.',
            'Payment received{% if order_number %} - {{ order_number }}{% endif %}',
            'We have received your payment of {{ currency }} {{ amount }}'
            '{% if order_number %} for order {{ order_number }}{% endif %}.\n\n'
            'Thank you.',
        ),
        'payment_failed': (
            'Payment failed',
            'Payment failed',
            'Your payment of {{ currency }} {{ amount }}'
            '{% if order_number %} for order {{ order_number }}{% endif %} did not go through.'
            '{% if failure_reason %} Reason: {{ failure_reason }}{% endif %}',
            'Payment failed{% if order_number %} - {{ order_number }}{% endif %}',
            'Your payment of {{ currency }} {{ amount }}'
            '{% if order_number %} for order {{ order_number }}{% endif %} did not go through.'
            '{% if failure_reason %}\n\nReason: {{ failure_reason }}{% endif %}\n\n'
            'Please try again or choose another payment method.',
        ),
        'booking_confirmed': (
            'Booking confirmed',
            'Booking confirmed',
            'Your booking for {{ slot_display }} is confirmed. Booking #{{ booking_id }}.',
            'Booking confirmed - {{ slot_display }}',
            'Your booking for {{ slot_display }} is confirmed.\n\n'
            'Booking number: {{ booking_id }}',
        ),
    },
    'zh-hans': {
        'order_created': (
            '订单已提交',
            '订单已提交',
            '感谢您的订购！订单 {{ order_number }} 已提交，合计 ¤{{ total }}。',
            '订单确认 - {{ order_number }}',
            '感谢您的订购！\n\n'
            '订单号：{{ order_number }}\n'
            '订单金额：¤{{ total }}\n\n'
            '发货后我们会再通知您。',
        ),
        'order_processing': (
            '订单备货中',
            '订单备货中',
            '订单 {{ order_number }} 正在备货。',
            '订单 {{ order_number }} 正在备货',
            '订单 {{ order_number }} 正在备货，发货后我们会再通知您。',
        ),
        'order_shipped': (
            '订单已发货',
            '订单已发货',
            '订单 {{ order_number }} 已发货。'
            '{% if tracking_number %}运单号：{{ tracking_number }}{% endif %}',
            '订单 {{ order_number }} 已发货',
            '订单 {{ order_number }} 已发货，请留意收货。\n'
            '{% if tracking_number %}\n运单号：{{ tracking_number }}{% endif %}'
            '{% if tracking_url %}\n物流查询：{{ tracking_url }}{% endif %}',
        ),
        'order_delivered': (
            '订单已送达',
            '订单已送达',
            '订单 {{ order_number }} 已送达，感谢您的惠顾！',
            '订单 {{ order_number }} 已送达',
            '订单 {{ order_number }} 已送达。\n\n'
            '感谢您的惠顾！',
        ),
        'order_cancelled': (
            '订单已取消',
            '订单已取消',
            '订单 {{ order_number }} 已取消。'
            '{% if cancellation_reason %}原因：{{ cancellation_reason }}{% endif %}',
            '订单 {{ order_number }} 已取消',
            '订单 {{ order_number }} 已取消。'
            '{% if cancellation_reason %}\n\n原因：{{ cancellation_reason }}{% endif %}\n\n'
            '如有疑问，请联系我们。',
        ),
        'order_refunded': (
            '订单已退款',
            '退款已处理',
            '订单 {{ order_number }} 的退款 ¤{{ refund_amount }} 已处理。',
            '订单 {{ order_number }} 退款通知',
            '订单 {{ order_number }} 的退款 ¤{{ refund_amount }} 已处理。\n\n'
            '款项将原路退回，到账时间以支付渠道为准。',
        ),
        'payment_received': (
            '已收到付款',
            '已收到付款',
            '已收到您{% if order_number %}订单 {{ order_number }} {% endif %}的付款 {{ currency }} {{ amount }}。',
            '已收到付款{% if order_number %} - {{ order_number }}{% endif %}',
            '已收到您{% if order_number %}订单 {{ order_number }} {% endif %}的付款 {{ currency }} {{ amount }}。\n\n'
            '感谢您的支付。',
        ),
        'payment_failed': (
            '付款失败',
            '付款失败',
            '您{% if order_number %}订单 {{ order_number }} {% endif %}的付款 {{ currency }} {{ amount }} 未成功。'
            '{% if failure_reason %}原因：{{ failure_reason }}{% endif %}',
            '付款失败{% if order_number %} - {{ order_number }}{% endif %}',
            '您{% if order_number %}订单 {{ order_number }} {% endif %}的付款 {{ currency }} {{ amount }} 未成功。'
            '{% if failure_reason %}\n\n原因：{{ failure_reason }}{% endif %}\n\n'
            '请重试或更换支付方式。',
        ),
        'booking_confirmed': (
            '预约已确认',
            '预约已确认',
            '您预约的 {{ slot_display }} 已确认，预约编号 {{ booking_id }}。',
            '预约已确认 - {{ slot_display }}',
            '您预约的 {{ slot_display }} 已确认。\n\n'
            '预约编号：{{ booking_id }}',
        ),
    },
}


def _languages(language: str) -> Tuple[str, str]:
    """``(language the rows are stored under, copy that fills them)``.

    Rows go under a code ``MessageService.get_template`` always tries: a Chinese
    workspace's own language, a candidate for every recipient, and ``en`` for
    everything else, the last candidate.
    """
    code = (language or '').strip().lower()
    if code.startswith('zh'):
        return code, 'zh-hans'
    return 'en', 'en'


def _available_variables(code: str, variables: List[str]) -> Dict[str, str]:
    """The guide shown beside the copy: the task's context plus the objects ``send_notification`` adds."""
    guide = {name: 'string' for name in variables}
    guide['customer'] = 'object'
    if not code.startswith('booking_'):
        guide['order'] = 'object'
    return guide


def _locale(workspace, language: Optional[str], currency: Optional[str]) -> Tuple[str, str]:
    """``language`` and ``currency``, each falling back to the workspace settings."""
    settings_obj = Settings.objects.filter(workspace=workspace).first()
    language = (language or '').strip() or getattr(settings_obj, 'default_language', '')
    currency = (currency or '').strip() or getattr(settings_obj, 'default_currency', '')
    return language, currency


def _seeded(code: str, language: str, currency: str) -> Tuple[str, Dict[str, Any]]:
    """``(row language, every other field)`` of the template seeding writes for ``code``.

    The fields seeding leaves blank are included, so a row compared against this
    also counts as changed when someone has added an SMS or push text.
    """
    row_language, copy_language = _languages(language)
    symbol = get_currency_profile(currency)['symbol']
    event, variables = _SPECS[code]
    name, title, body, subject, email_body = (
        text.replace(CURRENCY, symbol) for text in _COPY[copy_language][code]
    )
    return row_language, {
        'name': name,
        'event': event,
        'app_message_enabled': True,
        'app_message_title': title,
        'app_message_body': body,
        'email_enabled': False,
        'email_subject': subject,
        'email_body': email_body,
        'email_html_body': '',
        'sms_enabled': False,
        'sms_body': '',
        'push_enabled': False,
        'push_title': '',
        'push_body': '',
        'available_variables': _available_variables(code, variables),
        'is_active': True,
    }


def notification_template_name(code: str, language: str) -> str:
    """The name seeding gives the template for ``code`` in ``language``."""
    return _COPY[_languages(language)[1]][code][0]


def ensure_notification_templates(
    workspace,
    language: Optional[str] = None,
    currency: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Give ``workspace`` a template for every notification code it has none for.

    ``language`` and ``currency`` default to the workspace settings; provisioning
    passes the values it is saving. Returns ``language`` plus the ``created`` and
    ``existing`` codes. With ``dry_run`` nothing is written and ``created`` lists
    what would be.
    """
    language, currency = _locale(workspace, language, currency)
    row_language, _ = _languages(language)

    existing = set(
        MessageTemplate.objects.filter(workspace=workspace, code__in=NOTIFICATION_CODES)
        .values_list('code', flat=True)
    )
    created = [code for code in NOTIFICATION_CODES if code not in existing]
    if not dry_run:
        for code in created:
            _, fields = _seeded(code, language, currency)
            MessageTemplate.objects.get_or_create(
                workspace=workspace, code=code, language=row_language, defaults=fields,
            )
    return {
        'language': row_language,
        'created': created,
        'existing': [code for code in NOTIFICATION_CODES if code in existing],
    }


def relocalise_notification_templates(
    workspace,
    previous_language: str,
    previous_currency: str,
    language: Optional[str] = None,
    currency: Optional[str] = None,
    dry_run: bool = False,
) -> List[str]:
    """Rewrite in the workspace's new language and currency the templates seeded in its old ones.

    A template is rewritten only while it is still exactly what seeding wrote for
    ``previous_language`` and ``previous_currency``. Once anyone has changed it,
    even only to switch a channel on, it is left alone. So is a template whose
    code already has a row in the new language.

    ``language`` and ``currency`` default to the workspace settings. Returns the
    codes rewritten, or with ``dry_run`` the codes that would be. A code whose
    copy comes out the same, such as one without a price when only the currency
    changes, is not rewritten.
    """
    language, currency = _locale(workspace, language, currency)
    previous_row_language, _ = _languages(previous_language)
    templates = MessageTemplate.objects.filter(workspace=workspace, code__in=NOTIFICATION_CODES)
    taken = set(templates.values_list('code', 'language'))

    rewritten = set()
    for template in templates.filter(language=previous_row_language):
        _, before = _seeded(template.code, previous_language, previous_currency)
        if any(getattr(template, field) != value for field, value in before.items()):
            continue
        row_language, after = _seeded(template.code, language, currency)
        if (row_language, after) == (template.language, before):
            continue
        if row_language != template.language and (template.code, row_language) in taken:
            continue
        rewritten.add(template.code)
        if not dry_run:
            template.language = row_language
            for field, value in after.items():
                setattr(template, field, value)
            template.save()
    return [code for code in NOTIFICATION_CODES if code in rewritten]


def missing_notification_templates(workspace) -> List[str]:
    """Codes the workspace has no template for, of its own or inherited from the platform level.

    A workspace row that is switched off is not missing: turning a notification
    off is the shop's decision.
    """
    covered = set(
        MessageTemplate.objects.filter(workspace=workspace, code__in=NOTIFICATION_CODES)
        .values_list('code', flat=True)
    )
    covered.update(
        MessageTemplate.objects.filter(workspace__isnull=True, is_active=True, code__in=NOTIFICATION_CODES)
        .values_list('code', flat=True)
    )
    return [code for code in NOTIFICATION_CODES if code not in covered]

# -*- coding: utf-8 -*-
"""
Event handlers for shop module.
Listens to order events and triggers async notifications.
"""

import logging
from bfg.core.events import global_dispatcher

logger = logging.getLogger(__name__)


def on_order_created(event_data):
    """
    Handle order.created event.
    Triggers async notification.
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Import here to avoid circular imports
        from bfg.shop.tasks import send_order_created_notification
        
        # Trigger async task
        send_order_created_notification.delay(
            workspace_id=workspace.id,
            order_id=order.id
        )
        
        logger.info(
            f"Triggered order created notification for order {order.order_number}"
        )
        
    except Exception as e:
        logger.error(f"Error handling order.created event: {e}", exc_info=True)


def on_order_shipped(event_data):
    """
    Handle order.shipped event.
    Triggers async notification.
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Get consignment if available
        consignment_id = None
        consignment = event_data.get('data', {}).get('consignment')
        if consignment:
            consignment_id = consignment.id
        
        # Import here to avoid circular imports
        from bfg.shop.tasks import send_order_shipped_notification
        
        # Trigger async task
        send_order_shipped_notification.delay(
            workspace_id=workspace.id,
            order_id=order.id,
            consignment_id=consignment_id
        )
        
        logger.info(
            f"Triggered order shipped notification for order {order.order_number}"
        )
        
    except Exception as e:
        logger.error(f"Error handling order.shipped event: {e}", exc_info=True)


def on_order_delivered(event_data):
    """
    Handle order.delivered event.
    Triggers async notification.
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Import here to avoid circular imports
        from bfg.shop.tasks import send_order_delivered_notification
        
        # Trigger async task
        send_order_delivered_notification.delay(
            workspace_id=workspace.id,
            order_id=order.id
        )
        
        logger.info(
            f"Triggered order delivered notification for order {order.order_number}"
        )
        
    except Exception as e:
        logger.error(f"Error handling order.delivered event: {e}", exc_info=True)


def on_order_processing(event_data):
    """
    Handle order.processing event.
    Triggers async notification (optional).
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Import here to avoid circular imports
        from bfg.shop.tasks import send_order_processing_notification
        
        # Trigger async task
        send_order_processing_notification.delay(
            workspace_id=workspace.id,
            order_id=order.id
        )
        
        logger.info(
            f"Triggered order processing notification for order {order.order_number}"
        )
        
    except Exception as e:
        logger.error(f"Error handling order.processing event: {e}", exc_info=True)


def on_order_cancelled(event_data):
    """
    Handle order.cancelled event.
    Triggers async notification.
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        reason = event_data.get('data', {}).get('reason', '')
        
        # Import here to avoid circular imports
        from bfg.shop.tasks import send_order_cancelled_notification
        
        # Trigger async task
        send_order_cancelled_notification.delay(
            workspace_id=workspace.id,
            order_id=order.id,
            reason=reason
        )
        
        logger.info(
            f"Triggered order cancelled notification for order {order.order_number}"
        )
        
    except Exception as e:
        logger.error(f"Error handling order.cancelled event: {e}", exc_info=True)


def on_order_refunded(event_data):
    """
    Handle order.refunded event.
    Triggers async notification.
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        refund_amount = event_data.get('data', {}).get('refund_amount')
        
        # Import here to avoid circular imports
        from bfg.shop.tasks import send_order_refunded_notification
        
        # Trigger async task
        send_order_refunded_notification.delay(
            workspace_id=workspace.id,
            order_id=order.id,
            refund_amount=refund_amount
        )
        
        logger.info(
            f"Triggered order refunded notification for order {order.order_number}"
        )
        
    except Exception as e:
        logger.error(f"Error handling order.refunded event: {e}", exc_info=True)


def on_order_paid(event_data):
    """
    Handle order.paid event.
    Triggers async notification for payment received.
    """
    try:
        order = event_data.get('data', {}).get('order')
        if not order:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Get payment from order
        # Try to get the latest payment for this order
        from bfg.finance.models import Payment
        payment = Payment.objects.filter(
            order=order,
            workspace=workspace,
            status='completed'
        ).order_by('-created_at').first()
        
        if payment:
            # Payment notifications are handled by inbox.handlers
            # This is just for order.paid event, which may trigger payment notification
            # The actual payment.completed event will be handled by inbox.handlers
            logger.info(
                f"Order {order.order_number} paid, payment notification handled by payment.completed event"
            )
        
    except Exception as e:
        logger.error(f"Error handling order.paid event: {e}", exc_info=True)


def on_order_package_added(event_data):
    """
    Handle order.package.added event.
    Auto-update order to processing when first package is added (paid orders only).
    """
    try:
        data = event_data.get('data', {})
        order = data.get('order')
        if not order:
            return
        workspace = event_data.get('workspace')
        user = event_data.get('user')
        if not workspace:
            return
        if (order.payment_status != 'paid' or order.status not in ('pending', 'paid') or
                order.packages.count() != 1):
            return
        from bfg.shop.services import OrderService
        OrderService(workspace=workspace, user=user).update_order_status(order, 'processing')
    except Exception as e:
        logger.error(f"Error handling order.package.added event: {e}", exc_info=True)


def on_consignment_created(event_data):
    """
    Handle consignment.created event.
    Auto-update related orders to shipped when transport record is created.
    """
    try:
        data = event_data.get('data', {})
        consignment = data.get('consignment')
        if not consignment:
            return
        workspace = event_data.get('workspace')
        user = event_data.get('user')
        if not workspace:
            return
        from bfg.shop.services import OrderService
        order_svc = OrderService(workspace=workspace, user=user)
        for order in consignment.orders.all():
            if order.status not in ('cancelled', 'refunded', 'delivered'):
                order_svc.update_order_status(order, 'shipped')
    except Exception as e:
        logger.error(f"Error handling consignment.created event: {e}", exc_info=True)


def on_consignment_delivered(event_data):
    """
    Handle consignment.delivered event.
    Auto-update related orders to delivered when consignment is marked delivered.
    """
    try:
        data = event_data.get('data', {})
        consignment = data.get('consignment')
        if not consignment:
            return
        workspace = event_data.get('workspace')
        user = event_data.get('user')
        if not workspace:
            return
        from bfg.shop.services import OrderService
        order_svc = OrderService(workspace=workspace, user=user)
        for order in consignment.orders.all():
            if order.status not in ('cancelled', 'refunded'):
                order_svc.update_order_status(order, 'delivered')
    except Exception as e:
        logger.error(f"Error handling consignment.delivered event: {e}", exc_info=True)


def on_order_paid_analytics(event_data):
    """
    Report a paid order to GA4 as a ``purchase``.

    This is the only place order revenue reaches GA4. The web storefront's gtag
    sends page views and nothing else, and the WeChat mini-program cannot run gtag
    at all — so without this, the mini-program's entire contribution is invisible
    and no property has any revenue in it.

    Hung off ``order.paid`` rather than ``order.created`` because GA4's ``purchase``
    is a revenue event: counting orders that were placed but never paid would
    overstate it, and abandoned checkouts are the common case.
    """
    try:
        order = event_data.get('data', {}).get('order')
        workspace = event_data.get('workspace')
        if not order or not workspace:
            return

        from bfg.core.analytics import client_id_for_customer, track

        client_id = client_id_for_customer(order.customer_id, workspace.id)
        if not client_id:
            return

        items = [
            {
                'item_id': item.sku or str(item.product_id),
                'item_name': item.product_name,
                'item_variant': item.variant_name or None,
                'price': float(item.price),
                'quantity': item.quantity,
            }
            for item in order.items.all()
        ]

        params = {
            'transaction_id': order.order_number,
            'value': float(order.total),
            'tax': float(order.tax),
            'shipping': float(order.shipping_cost),
            'currency': _order_currency(workspace),
            'items': items,
            # The whole point of the exercise: lets GA4 separate mini-program
            # revenue from web revenue, which is otherwise unknowable once both
            # arrive through the same server-side stream.
            'sales_channel': order.sales_channel.code if order.sales_channel else 'unknown',
        }

        track(workspace.id, client_id, 'purchase', params, user_id=order.customer_id)
    except Exception as e:
        # Analytics must never break order processing.
        logger.error(f"Error reporting order.paid to GA4: {e}", exc_info=True)


def _order_currency(workspace):
    """
    The currency to report the sale in.

    Orders carry no currency of their own — a workspace prices everything in its
    single default — so that setting is the only source. GA4 discards a `purchase`
    whose currency is missing or malformed, hence the explicit fallback.
    """
    from bfg.common.constants import DEFAULT_CURRENCY_CODE
    from bfg.common.models import Settings

    settings_obj = Settings.objects.filter(workspace=workspace).only('default_currency').first()
    return (getattr(settings_obj, 'default_currency', None) or DEFAULT_CURRENCY_CODE).upper()


# Register event listeners
def register_event_handlers():
    """Register all order event handlers."""
    global_dispatcher.listen('order.created', on_order_created)
    global_dispatcher.listen('order.package.added', on_order_package_added)
    global_dispatcher.listen('consignment.created', on_consignment_created)
    global_dispatcher.listen('consignment.delivered', on_consignment_delivered)
    global_dispatcher.listen('order.processing', on_order_processing)
    global_dispatcher.listen('order.shipped', on_order_shipped)
    global_dispatcher.listen('order.delivered', on_order_delivered)
    global_dispatcher.listen('order.cancelled', on_order_cancelled)
    global_dispatcher.listen('order.refunded', on_order_refunded)
    global_dispatcher.listen('order.paid', on_order_paid)
    global_dispatcher.listen('order.paid', on_order_paid_analytics)

    logger.info("Registered shop order event handlers")


# Auto-register handlers when module is imported
register_event_handlers()

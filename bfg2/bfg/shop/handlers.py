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
    
    logger.info("Registered shop order event handlers")


# Auto-register handlers when module is imported
register_event_handlers()

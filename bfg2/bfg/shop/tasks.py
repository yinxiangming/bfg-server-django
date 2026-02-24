# -*- coding: utf-8 -*-
"""
Celery tasks for shop module.
Handles scheduled price changes, order notifications, and other background tasks.
"""

from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task
def activate_scheduled_prices():
    """
    Activate scheduled price changes that have reached their effective time.
    Should be run every minute via celery beat.
    """
    from bfg.shop.services.product_price_service import ProductPriceService
    
    service = ProductPriceService()
    result = service.activate_pending_price_changes()
    
    if result['activated_count'] > 0:
        logger.info(
            f"Successfully activated {result['activated_count']} scheduled price changes"
        )
    
    if result['failed_count'] > 0:
        logger.error(
            f"Failed to activate {result['failed_count']} price changes. "
            f"Errors: {result['errors']}"
        )
    
    return result


# Order notification tasks
# These tasks handle order-related notifications via the inbox service

@shared_task(bind=True, max_retries=3)
def send_order_created_notification(self, workspace_id: int, order_id: int):
    """Send order created notification."""
    try:
        from bfg.shop.models import Order
        from bfg.inbox.tasks import send_notification
        
        order = Order.objects.select_related('customer', 'workspace').get(
            id=order_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data (no Django model objects)
        context_data = {
            'order_number': order.order_number,
            'total': str(order.total),
            'subtotal': str(order.subtotal),
            'shipping_cost': str(order.shipping_cost),
            'tax': str(order.tax),
            'discount': str(order.discount),
            'created_at': order.created_at.isoformat() if order.created_at else '',
            'status': order.status,
            'payment_status': order.payment_status,
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=order.customer.id,
            template_code='order_created',
            context_data=context_data,
            order_id=order.id
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send order created notification for order {order_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_order_shipped_notification(
    self,
    workspace_id: int,
    order_id: int,
    consignment_id: int = None
):
    """Send order shipped notification."""
    try:
        from bfg.shop.models import Order
        from bfg.delivery.models import Consignment
        from bfg.inbox.tasks import send_notification
        
        order = Order.objects.select_related('customer', 'workspace').get(
            id=order_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'order_number': order.order_number,
            'shipped_at': order.shipped_at.isoformat() if order.shipped_at else '',
        }
        
        # Add consignment info if available
        if consignment_id:
            try:
                consignment = Consignment.objects.get(
                    id=consignment_id,
                    workspace_id=workspace_id
                )
                context_data['tracking_number'] = consignment.consignment_number
                context_data['tracking_url'] = consignment.tracking_url or ''
            except Consignment.DoesNotExist:
                pass
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=order.customer.id,
            template_code='order_shipped',
            context_data=context_data,
            order_id=order.id
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send order shipped notification for order {order_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_order_delivered_notification(self, workspace_id: int, order_id: int):
    """Send order delivered notification."""
    try:
        from bfg.shop.models import Order
        from bfg.inbox.tasks import send_notification
        
        order = Order.objects.select_related('customer', 'workspace').get(
            id=order_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'order_number': order.order_number,
            'delivered_at': order.delivered_at.isoformat() if order.delivered_at else '',
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=order.customer.id,
            template_code='order_delivered',
            context_data=context_data,
            order_id=order.id
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send order delivered notification for order {order_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_order_cancelled_notification(
    self,
    workspace_id: int,
    order_id: int,
    reason: str = ''
):
    """Send order cancelled notification."""
    try:
        from bfg.shop.models import Order
        from bfg.inbox.tasks import send_notification
        
        order = Order.objects.select_related('customer', 'workspace').get(
            id=order_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'order_number': order.order_number,
            'cancellation_reason': reason,
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=order.customer.id,
            template_code='order_cancelled',
            context_data=context_data,
            order_id=order.id
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send order cancelled notification for order {order_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_order_refunded_notification(
    self,
    workspace_id: int,
    order_id: int,
    refund_amount: str = None
):
    """Send order refunded notification."""
    try:
        from bfg.shop.models import Order
        from bfg.inbox.tasks import send_notification
        
        order = Order.objects.select_related('customer', 'workspace').get(
            id=order_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'order_number': order.order_number,
            'refund_amount': refund_amount or str(order.total),
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=order.customer.id,
            template_code='order_refunded',
            context_data=context_data,
            order_id=order.id
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send order refunded notification for order {order_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_order_processing_notification(self, workspace_id: int, order_id: int):
    """Send order processing notification (optional)."""
    try:
        from bfg.shop.models import Order
        from bfg.inbox.tasks import send_notification
        
        order = Order.objects.select_related('customer', 'workspace').get(
            id=order_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'order_number': order.order_number,
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=order.customer.id,
            template_code='order_processing',
            context_data=context_data,
            order_id=order.id
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send order processing notification for order {order_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

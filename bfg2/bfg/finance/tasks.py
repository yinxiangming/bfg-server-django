# -*- coding: utf-8 -*-
"""
Celery tasks for finance module.
Handles payment-related notifications.
"""

from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_payment_received_notification(self, workspace_id: int, payment_id: int):
    """Send payment received notification."""
    try:
        from bfg.finance.models import Payment
        from bfg.inbox.tasks import send_notification
        
        payment = Payment.objects.select_related(
            'customer', 'order', 'currency', 'workspace'
        ).get(
            id=payment_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'amount': str(payment.amount),
            'currency': payment.currency.code if payment.currency else 'USD',
            'order_number': payment.order.order_number if payment.order else '',
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=payment.customer.id,
            template_code='payment_received',
            context_data=context_data,
            order_id=payment.order.id if payment.order else None
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send payment received notification for payment {payment_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def send_payment_failed_notification(
    self,
    workspace_id: int,
    payment_id: int,
    failure_reason: str = ''
):
    """Send payment failed notification."""
    try:
        from bfg.finance.models import Payment
        from bfg.inbox.tasks import send_notification
        
        payment = Payment.objects.select_related(
            'customer', 'order', 'currency', 'workspace'
        ).get(
            id=payment_id,
            workspace_id=workspace_id
        )
        
        # Build serializable context data
        context_data = {
            'amount': str(payment.amount),
            'currency': payment.currency.code if payment.currency else 'USD',
            'order_number': payment.order.order_number if payment.order else '',
            'failure_reason': failure_reason,
        }
        
        send_notification.delay(
            workspace_id=workspace_id,
            customer_id=payment.customer.id,
            template_code='payment_failed',
            context_data=context_data,
            order_id=payment.order.id if payment.order else None
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send payment failed notification for payment {payment_id}: {exc}",
            exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

# -*- coding: utf-8 -*-
"""
Event handlers for finance module.
Listens to payment events and triggers async notifications.
"""

import logging
from bfg.core.events import global_dispatcher

logger = logging.getLogger(__name__)


def on_payment_completed(event_data):
    """
    Handle payment.completed event.
    Triggers async notification for payment received.
    """
    try:
        payment = event_data.get('data', {}).get('payment')
        if not payment:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Import here to avoid circular imports
        from bfg.finance.tasks import send_payment_received_notification
        
        # Trigger async task
        send_payment_received_notification.delay(
            workspace_id=workspace.id,
            payment_id=payment.id
        )
        
        logger.info(
            f"Triggered payment received notification for payment {payment.id}"
        )
        
    except Exception as e:
        logger.error(f"Error handling payment.completed event: {e}", exc_info=True)


def on_payment_failed(event_data):
    """
    Handle payment.failed event.
    Triggers async notification for payment failure.
    """
    try:
        payment = event_data.get('data', {}).get('payment')
        if not payment:
            return
        
        workspace = event_data.get('workspace')
        if not workspace:
            return
        
        # Get failure reason from gateway response
        failure_reason = ''
        if payment.gateway_response:
            if isinstance(payment.gateway_response, dict):
                failure_reason = payment.gateway_response.get('error', '')
            else:
                failure_reason = str(payment.gateway_response)
        
        # Import here to avoid circular imports
        from bfg.finance.tasks import send_payment_failed_notification
        
        # Trigger async task
        send_payment_failed_notification.delay(
            workspace_id=workspace.id,
            payment_id=payment.id,
            failure_reason=failure_reason
        )
        
        logger.info(
            f"Triggered payment failed notification for payment {payment.id}"
        )
        
    except Exception as e:
        logger.error(f"Error handling payment.failed event: {e}", exc_info=True)


# Register event listeners
def register_event_handlers():
    """Register payment event handlers."""
    global_dispatcher.listen('payment.completed', on_payment_completed)
    global_dispatcher.listen('payment.failed', on_payment_failed)
    
    logger.info("Registered finance payment event handlers")


# Auto-register handlers when module is imported
register_event_handlers()

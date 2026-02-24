# -*- coding: utf-8 -*-
"""
Celery tasks for inbox module.
Handles generic notification sending tasks.
Order-specific notification tasks are in bfg.shop.tasks
"""

from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_notification(
    self,
    workspace_id: int,
    customer_id: int,
    template_code: str,
    context_data: dict,
    order_id: int = None
):
    """
    Send notification via multiple channels (Email, SMS, Push) asynchronously.
    Generic notification sending task that can be used by any module.
    Respects customer preferences and template settings.
    
    Args:
        workspace_id: Workspace ID
        customer_id: Customer ID
        template_code: Message template code
        context_data: Template context data (must be JSON serializable)
        order_id: Optional order ID to load order object for template
    """
    try:
        from bfg.common.models import Workspace, Customer
        from bfg.inbox.services.message_service import MessageService
        
        # Get workspace and customer
        workspace = Workspace.objects.get(id=workspace_id)
        customer = Customer.objects.select_related('user').get(
            id=customer_id,
            workspace=workspace
        )
        
        # Get customer preferences (via user)
        user_prefs = getattr(customer.user, 'preferences', None)
        if not user_prefs:
            from bfg.common.models.preferences import UserPreferences
            user_prefs = UserPreferences.get_or_create_for_user(customer.user)
        
        # Check if customer wants order update notifications (for order-related notifications)
        # This check is only relevant for order-related templates
        if template_code.startswith('order_') and not user_prefs.notify_order_updates:
            logger.info(
                f"Skipping {template_code} notification for customer {customer_id}: "
                f"order updates disabled in preferences"
            )
            return
        
        # Load order object if order_id is provided (for template access)
        if order_id:
            from bfg.shop.models import Order
            try:
                order = Order.objects.select_related(
                    'customer', 'workspace', 'store'
                ).prefetch_related('items').get(
                    id=order_id,
                    workspace_id=workspace_id
                )
                # Add order and customer objects to context for template
                context_data['order'] = order
                context_data['customer'] = customer
            except Order.DoesNotExist:
                logger.warning(f"Order {order_id} not found, continuing without order object")
        else:
            # Add customer object to context
            context_data['customer'] = customer
        
        # Create message service
        message_service = MessageService(workspace=workspace, user=None)
        
        # Send message from template (will respect template settings and customer preferences)
        # The send_from_template method will check template.email_enabled, template.sms_enabled, etc.
        # and customer preferences to decide which channels to use
        # Don't force channels - let send_from_template check both template and preferences
        message = message_service.send_from_template(
            recipients=[customer],
            template_code=template_code,
            context_data=context_data,
            language=getattr(customer, 'language', None) or 'en',
        )
        
        # SMS and Push are handled by MessageService.send_from_template
        # which respects template settings and customer preferences
        # The message.send_sms and message.send_push flags indicate
        # whether those channels were enabled
        
        logger.info(
            f"Successfully sent {template_code} notification to customer {customer_id} "
            f"(email={message.send_email}, sms={message.send_sms}, push={message.send_push}) "
            f"for workspace {workspace_id}"
        )
        
    except Exception as exc:
        logger.error(
            f"Failed to send {template_code} notification to customer {customer_id}: {exc}",
            exc_info=True
        )
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# Generic notification sending task
# Business-specific notification tasks are in their respective modules:
# - Order notifications: bfg.shop.tasks
# - Payment notifications: bfg.finance.tasks

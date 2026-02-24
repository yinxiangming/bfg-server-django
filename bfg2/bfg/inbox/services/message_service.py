"""
BFG Inbox Module Services

Message and notification services
"""

from typing import Any, Optional, List, Dict
from django.db import transaction
from django.utils import timezone
from django.template import Template, Context
from bfg.core.services import BaseService
from bfg.inbox.models import Message, MessageRecipient, MessageTemplate, SMSMessage
from bfg.common.models import Customer
from typing import Optional


class MessageService(BaseService):
    """
    Message and notification service
    
    Handles sending in-app messages and notifications
    """
    
    @transaction.atomic
    def send_message(
        self,
        recipients: List[Customer],
        subject: str,
        message: str,
        **kwargs: Any
    ) -> Message:
        """
        Send message to recipients
        
        Args:
            recipients: List of Customer instances
            subject: Message subject
            message: Message content
            **kwargs: Additional fields
            
        Returns:
            Message: Created message instance
        """
        # Create message
        msg = Message.objects.create(
            workspace=self.workspace,
            subject=subject,
            message=message,
            message_type=kwargs.get('message_type', 'notification'),
            sender=self.user,
            action_url=kwargs.get('action_url', ''),
            action_label=kwargs.get('action_label', ''),
            send_email=kwargs.get('send_email', False),
            send_sms=kwargs.get('send_sms', False),
            send_push=kwargs.get('send_push', False),
        )
        
        # Create recipients
        for recipient in recipients:
            MessageRecipient.objects.create(
                message=msg,
                recipient=recipient,
            )
        
        # Emit event
        self.emit_event('message.sent', {
            'message': msg,
            'recipient_count': len(recipients)
        })
        
        return msg
    
    @transaction.atomic
    def send_from_template(
        self,
        recipients: List[Customer],
        template_code: str,
        context_data: Dict[str, Any],
        language: str = 'en',
        force_email: Optional[bool] = None,
        force_sms: Optional[bool] = None,
        force_push: Optional[bool] = None
    ) -> Message:
        """
        Send message using template
        
        Args:
            recipients: List of Customer instances
            template_code: Template code
            context_data: Template context variables
            language: Language code
            force_email: Override email sending (None = use template + customer preference)
            force_sms: Override SMS sending (None = use template + customer preference)
            force_push: Override push sending (None = use template + customer preference)
            
        Returns:
            Message: Created message instance
        """
        # Get template
        template = MessageTemplate.objects.filter(
            workspace=self.workspace,
            code=template_code,
            language=language,
            is_active=True
        ).first()
        
        if not template:
            from bfg.core.exceptions import ValidationError
            raise ValidationError(f"Template '{template_code}' not found")
        
        # Log template status for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(
            f"Template '{template_code}' found: app_message_enabled={template.app_message_enabled}, "
            f"email_enabled={template.email_enabled}, is_active={template.is_active}"
        )
        
        # Determine which channels to use based on template and customer preferences
        # For simplicity, we'll use the first recipient's preferences
        # In production, you might want to send separate messages per recipient
        send_email = template.email_enabled
        send_sms = template.sms_enabled
        send_push = template.push_enabled
        
        # Apply customer preferences if provided
        if recipients:
            customer = recipients[0]
            # Get customer preferences via user
            if hasattr(customer, 'user') and hasattr(customer.user, 'preferences'):
                prefs = customer.user.preferences
                # Only send if customer has enabled this channel
                if force_email is None:
                    send_email = send_email and prefs.email_notifications
                if force_sms is None:
                    send_sms = send_sms and prefs.sms_notifications
                if force_push is None:
                    send_push = send_push and prefs.push_notifications
        
        # Apply force overrides
        if force_email is not None:
            send_email = force_email and template.email_enabled
        if force_sms is not None:
            send_sms = force_sms and template.sms_enabled
        if force_push is not None:
            send_push = force_push and template.push_enabled
        
        # Render template
        if template.app_message_enabled:
            subject = self._render_template(template.app_message_title, context_data)
            message = self._render_template(template.app_message_body, context_data)
            
            # Create message
            msg = self.send_message(
                recipients,
                subject,
                message,
                message_type='notification',
                send_email=send_email,
                send_sms=send_sms,
                send_push=send_push,
            )
            
            # Log message creation for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"Created Inbox Message ID {msg.id} for template '{template_code}' "
                f"with {len(recipients)} recipient(s)"
            )
            
            # Send Email if enabled
            if send_email and template.email_enabled:
                for recipient in recipients:
                    # Check customer email preference again and get email address
                    if hasattr(recipient, 'user') and hasattr(recipient.user, 'preferences'):
                        prefs = recipient.user.preferences
                        if prefs.email_notifications and recipient.user.email:
                            try:
                                self._send_email(
                                    recipient,
                                    template,
                                    context_data,
                                    subject
                                )
                            except Exception as e:
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.error(f"Failed to send email to {recipient.id}: {e}")
            
            # Send SMS if enabled
            if send_sms and template.sms_enabled and template.sms_body:
                for recipient in recipients:
                    # Check customer SMS preference again
                    if hasattr(recipient, 'user') and hasattr(recipient.user, 'preferences'):
                        prefs = recipient.user.preferences
                        if prefs.sms_notifications:
                            try:
                                sms_service = SMSService(workspace=self.workspace, user=self.user)
                                sms_body = self._render_template(template.sms_body, context_data)
                                sms_service.send_sms(recipient, sms_body[:160])
                            except Exception as e:
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.error(f"Failed to send SMS to {recipient.id}: {e}")
            
            # Send Push notification if enabled
            if send_push and template.push_enabled:
                for recipient in recipients:
                    # Check customer push preference again
                    if hasattr(recipient, 'user') and hasattr(recipient.user, 'preferences'):
                        prefs = recipient.user.preferences
                        if prefs.push_notifications:
                            try:
                                # Render push notification content
                                push_title = self._render_template(template.push_title, context_data) if template.push_title else subject
                                push_body = self._render_template(template.push_body, context_data) if template.push_body else message[:255]
                                
                                # Send push notification (implement based on your push provider)
                                # This is a placeholder - implement actual push sending
                                self._send_push_notification(
                                    recipient,
                                    push_title,
                                    push_body,
                                    action_url=msg.action_url
                                )
                            except Exception as e:
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.error(f"Failed to send push to {recipient.id}: {e}")
            
            return msg
        
        from bfg.core.exceptions import ValidationError
        raise ValidationError("Template does not have app message enabled")
    
    def _send_email(
        self,
        customer: Customer,
        template: 'MessageTemplate',
        context_data: Dict[str, Any],
        fallback_subject: str
    ) -> None:
        """
        Send email to customer using template (workspace EmailConfig).
        """
        import logging
        logger = logging.getLogger(__name__)
        recipient_email = customer.user.email
        if not recipient_email:
            logger.warning("Customer %s has no email address", customer.id)
            return
        email_subject = self._render_template(
            template.email_subject or fallback_subject,
            context_data
        )
        try:
            from bfg.common.services import EmailService
            if template.email_body and not template.email_html_body:
                body_plain = self._render_template(template.email_body, context_data)
                EmailService.send_email(
                    self.workspace,
                    to_list=[recipient_email],
                    subject=email_subject,
                    body_plain=body_plain,
                )
            elif template.email_html_body:
                text_content = self._render_template(template.email_body, context_data) if template.email_body else ''
                html_content = self._render_template(template.email_html_body, context_data)
                EmailService.send_email(
                    self.workspace,
                    to_list=[recipient_email],
                    subject=email_subject,
                    body_plain=text_content,
                    body_html=html_content,
                )
            elif template.app_message_body:
                body_plain = self._render_template(template.app_message_body, context_data)
                EmailService.send_email(
                    self.workspace,
                    to_list=[recipient_email],
                    subject=email_subject,
                    body_plain=body_plain,
                )
        except ValueError as e:
            logger.warning("Inbox email skip (no workspace email config): %s", e)
        except Exception as e:
            logger.exception("Inbox email send failed to %s: %s", recipient_email, e)
    
    def _send_push_notification(
        self,
        customer: Customer,
        title: str,
        body: str,
        action_url: str = ''
    ) -> None:
        """
        Send push notification to customer.
        
        This is a placeholder implementation. In production, integrate with:
        - Firebase Cloud Messaging (FCM)
        - Apple Push Notification Service (APNS)
        - OneSignal
        - Pusher Beams
        
        Args:
            customer: Customer instance
            title: Push notification title
            body: Push notification body
            action_url: Optional action URL
        """
        # Placeholder - implement actual push notification sending
        # For now, just log that push would be sent
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Push notification would be sent to customer {customer.id}: {title} - {body}")
        # In production, integrate with your push notification provider here
    
    def _render_template(self, template_str: str, context_data: Dict[str, Any]) -> str:
        """
        Render Django template string
        
        Args:
            template_str: Template string
            context_data: Context variables
            
        Returns:
            str: Rendered template
        """
        template = Template(template_str)
        context = Context(context_data)
        return template.render(context)
    
    def mark_as_read(
        self,
        message_recipient: MessageRecipient
    ) -> MessageRecipient:
        """
        Mark message as read
        
        Args:
            message_recipient: MessageRecipient instance
            
        Returns:
            MessageRecipient: Updated instance
        """
        if not message_recipient.is_read:
            message_recipient.is_read = True
            message_recipient.read_at = timezone.now()
            message_recipient.save()
        
        return message_recipient
    
    def get_unread_count(self, customer: Customer) -> int:
        """
        Get unread message count for customer
        
        Args:
            customer: Customer instance
            
        Returns:
            int: Unread message count
        """
        return MessageRecipient.objects.filter(
            recipient=customer,
            is_read=False,
            is_deleted=False
        ).count()


class NotificationService(BaseService):
    """
    High-level notification service for system events
    
    Handles automatic notifications for order events, etc.
    """
    
    def notify_order_created(self, order) -> None:
        """Notify customer about order creation"""
        message_service = MessageService(workspace=self.workspace, user=self.user)
        message_service.send_from_template(
            recipients=[order.customer],
            template_code='order_created',
            context_data={
                'order': order,
                'customer': order.customer,
                'total': order.total,
            }
        )
    
    def notify_order_shipped(self, order, consignment) -> None:
        """Notify customer about order shipment"""
        message_service = MessageService(workspace=self.workspace, user=self.user)
        message_service.send_from_template(
            recipients=[order.customer],
            template_code='order_shipped',
            context_data={
                'order': order,
                'consignment': consignment,
                'tracking_number': consignment.consignment_number,
            }
        )
    
    def notify_payment_received(self, payment) -> None:
        """Notify customer about payment received"""
        message_service = MessageService(workspace=self.workspace, user=self.user)
        message_service.send_from_template(
            recipients=[payment.customer],
            template_code='payment_received',
            context_data={
                'payment': payment,
                'amount': payment.amount,
                'currency': payment.currency.code,
            }
        )


class SMSService(BaseService):
    """
    SMS sending service
    
    Integrates with SMS providers (Twilio, etc.)
    """
    
    @transaction.atomic
    def send_sms(
        self,
        customer: Customer,
        message: str,
        phone_number: Optional[str] = None
    ) -> SMSMessage:
        """
        Send SMS to customer
        
        Args:
            customer: Customer instance
            message: SMS message (max 160 chars)
            phone_number: Phone number (uses customer's if not provided)
            
        Returns:
            SMSMessage: Created SMS instance
        """
        if not phone_number:
            # Get customer's phone from address or profile
            phone_number = self._get_customer_phone(customer)
        
        # Create SMS record
        sms = SMSMessage.objects.create(
            workspace=self.workspace,
            customer=customer,
            phone_number=phone_number,
            message=message[:160],  # Enforce SMS limit
            status='pending',
        )
        
        # Send through provider (simplified stub)
        try:
            provider_response = self._send_via_provider(phone_number, message)
            
            sms.status = 'sent'
            sms.sent_at = timezone.now()
            sms.provider = provider_response.get('provider', 'twilio')
            sms.provider_id = provider_response.get('message_sid', '')
            sms.provider_response = provider_response
            sms.save()
            
        except Exception as e:
            sms.status = 'failed'
            sms.provider_response = {'error': str(e)}
            sms.save()
        
        return sms
    
    def _get_customer_phone(self, customer: Customer) -> str:
        """Get customer's phone number"""
        # Try to get from default address or customer profile
        # This is simplified - implement based on your data model
        if hasattr(customer, 'phone'):
            return customer.phone or ''
        # Try to get from user profile or addresses
        if hasattr(customer, 'user') and hasattr(customer.user, 'phone'):
            return customer.user.phone or ''
        return ''
    
    def _send_push_notification(
        self,
        customer: Customer,
        title: str,
        body: str,
        action_url: str = ''
    ) -> None:
        """
        Send push notification to customer.
        
        This is a placeholder implementation. In production, integrate with:
        - Firebase Cloud Messaging (FCM)
        - Apple Push Notification Service (APNS)
        - OneSignal
        - Pusher Beams
        
        Args:
            customer: Customer instance
            title: Push notification title
            body: Push notification body
            action_url: Optional action URL
        """
        # TODO: Implement actual push notification sending
        # Example with FCM:
        # from firebase_admin import messaging
        # message = messaging.Message(
        #     notification=messaging.Notification(title=title, body=body),
        #     token=customer.fcm_token,
        #     data={'action_url': action_url} if action_url else {}
        # )
        # messaging.send(message)
        
        # For now, just log
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Push notification prepared for customer {customer.id}: {title}")
    
    def _send_via_provider(
        self,
        phone_number: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send SMS via provider (simplified stub)
        
        In production, integrate with:
        - Twilio: twilio.rest.Client.messages.create()
        - Plivo: plivo.RestClient.messages.create()
        - AWS SNS: sns.publish()
        """
        # Simplified stub
        return {
            'success': True,
            'provider': 'twilio',
            'message_sid': f'SM{timezone.now().timestamp()}',
            'status': 'sent',
        }

"""
BFG Inbox Module Services

Message and notification services
"""

from typing import Any, Optional, List, Dict
from collections import OrderedDict
from django.db import transaction
from django.utils import timezone
from django.template import Template, Context
from bfg.core.services import BaseService
from bfg.inbox.models import Message, MessageRecipient, MessageTemplate, SMSMessage
from bfg.common.models import Customer
from typing import Optional


def _recipient_preferences(recipient: Customer) -> Any:
    """Return a recipient's UserPreferences, or None when absent.

    Channels gate per recipient on these preferences; a recipient without a
    linked user (or without preferences) is skipped, matching the historical
    behaviour of the hard-coded send loops.
    """
    if hasattr(recipient, 'user') and hasattr(recipient.user, 'preferences'):
        return recipient.user.preferences
    return None


class ChannelSender:
    """Extension seam for a notification channel.

    ``send_from_template`` dispatches a notification to every registered
    ChannelSender, applying each recipient's preferences independently. The
    built-in email/SMS/push channels are registered instances of this class;
    extensions (e.g. PackGo WeChat) register additional channels through
    :meth:`MessageService.register_channel`, so the core orchestrates
    per-recipient delivery without knowing about the concrete channel.

    The in-app message is NOT a ChannelSender: it stays a built-in default
    created directly by ``send_from_template``.
    """

    #: Unique channel key (e.g. ``"email"``); also matched against the
    #: ``force_<name>`` overrides of ``send_from_template``.
    name: str = ''

    def template_enabled(self, template: MessageTemplate) -> bool:
        """Whether this channel is turned on for the given template."""
        raise NotImplementedError

    def recipient_enabled(self, recipient: Customer) -> bool:
        """Whether this recipient opted in to this channel."""
        raise NotImplementedError

    def send(
        self,
        service: 'MessageService',
        recipient: Customer,
        template: MessageTemplate,
        context_data: Dict[str, Any],
        subject: str,
        message: str,
        action_url: str,
    ) -> None:
        """Deliver the rendered notification to a single recipient."""
        raise NotImplementedError


class _EmailChannel(ChannelSender):
    name = 'email'

    def template_enabled(self, template: MessageTemplate) -> bool:
        return template.email_enabled

    def recipient_enabled(self, recipient: Customer) -> bool:
        prefs = _recipient_preferences(recipient)
        return bool(prefs and prefs.email_notifications and recipient.user.email)

    def send(self, service, recipient, template, context_data, subject, message, action_url) -> None:
        service._send_email(recipient, template, context_data, subject)


class _SMSChannel(ChannelSender):
    name = 'sms'

    def template_enabled(self, template: MessageTemplate) -> bool:
        return template.sms_enabled and bool(template.sms_body)

    def recipient_enabled(self, recipient: Customer) -> bool:
        prefs = _recipient_preferences(recipient)
        return bool(prefs and prefs.sms_notifications)

    def send(self, service, recipient, template, context_data, subject, message, action_url) -> None:
        sms_service = SMSService(workspace=service.workspace, user=service.user)
        sms_body = service._render_template(template.sms_body, context_data)
        sms_service.send_sms(recipient, sms_body[:160])


class _PushChannel(ChannelSender):
    name = 'push'

    def template_enabled(self, template: MessageTemplate) -> bool:
        return template.push_enabled

    def recipient_enabled(self, recipient: Customer) -> bool:
        prefs = _recipient_preferences(recipient)
        return bool(prefs and prefs.push_notifications)

    def send(self, service, recipient, template, context_data, subject, message, action_url) -> None:
        push_title = (
            service._render_template(template.push_title, context_data)
            if template.push_title else subject
        )
        push_body = (
            service._render_template(template.push_body, context_data)
            if template.push_body else message[:255]
        )
        service._send_push_notification(recipient, push_title, push_body, action_url=action_url)


class MessageService(BaseService):
    """
    Message and notification service

    Handles sending in-app messages and notifications
    """

    # Ordered registry of pluggable notification channels. Built-in
    # email/SMS/push are registered at import time; extensions add channels
    # (e.g. PackGo WeChat) via ``register_channel``. The in-app message is a
    # built-in default and is NOT in this registry.
    _channels: "OrderedDict[str, ChannelSender]" = OrderedDict()

    @classmethod
    def register_channel(cls, sender: ChannelSender) -> None:
        """Register (or replace) a notification channel by its ``name``.

        Idempotent per name: re-registering the same name replaces the sender
        while keeping the original dispatch position.
        """
        if not getattr(sender, 'name', ''):
            raise ValueError("ChannelSender must define a non-empty name")
        cls._channels[sender.name] = sender

    @classmethod
    def unregister_channel(cls, name: str) -> None:
        """Remove a registered channel (no-op if absent)."""
        cls._channels.pop(name, None)

    @classmethod
    def get_channels(cls) -> List[ChannelSender]:
        """Registered channels in dispatch order."""
        return list(cls._channels.values())

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

        self.deliver_existing_message(msg, recipients)
        
        return msg

    def deliver_existing_message(
        self,
        message_obj: Message,
        recipients: List[Customer],
    ) -> None:
        if not message_obj.send_email:
            return

        for recipient in recipients:
            recipient_email = getattr(getattr(recipient, 'user', None), 'email', '')
            if not recipient_email:
                continue
            preferences = getattr(getattr(recipient, 'user', None), 'preferences', None)
            if preferences and hasattr(preferences, 'email_notifications') and not preferences.email_notifications:
                continue
            try:
                from bfg.common.services import EmailService
                EmailService.send_email(
                    self.workspace,
                    to_list=[recipient_email],
                    subject=message_obj.subject,
                    body_plain=message_obj.message,
                )
            except ValueError:
                pass
            except Exception:
                import logging
                logger = logging.getLogger(__name__)
                logger.exception("Failed to send direct inbox email to customer %s", recipient.id)
    
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
    ) -> Optional[Message]:
        """
        Send message using template

        Channels are chosen from the template's per-channel ``*_enabled`` flags
        (and any ``force_*`` override); each recipient's UserPreferences are then
        applied independently per channel. Templates without an in-app message
        (``app_message_enabled=False``) send email/SMS/push only.

        Args:
            recipients: List of Customer instances
            template_code: Template code
            context_data: Template context variables
            language: Language code
            force_email: Override email channel on/off (None = use template flag)
            force_sms: Override SMS channel on/off (None = use template flag)
            force_push: Override push channel on/off (None = use template flag)

        Returns:
            The created in-app Message, or None when the template only targets
            email/SMS/push (no in-app message).
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
        
        # Channel intent comes from the template flags (plus explicit force
        # overrides) ONLY. Per-recipient preferences are enforced inside each
        # send loop below, so one recipient opting out can no longer suppress a
        # channel for the whole batch (previously the *first* recipient's
        # preferences decided the channel for everyone).
        send_email = (force_email if force_email is not None else True) and template.email_enabled
        send_sms = (force_sms if force_sms is not None else True) and template.sms_enabled
        send_push = (force_push if force_push is not None else True) and template.push_enabled

        # The in-app message is optional: a template may target only
        # email/SMS/push. Previously this method raised when app_message_enabled
        # was False, making email-only templates impossible.
        msg = None
        subject = ''
        message = ''
        if template.app_message_enabled:
            subject = self._render_template(template.app_message_title, context_data)
            message = self._render_template(template.app_message_body, context_data)

            # Create the in-app message WITHOUT auto-delivering email/SMS/push:
            # send_from_template performs templated per-channel delivery below, so
            # passing the flags here would double-send (send_message's
            # deliver_existing_message also dispatches email).
            msg = self.send_message(
                recipients,
                subject,
                message,
                message_type='notification',
                send_email=False,
                send_sms=False,
                send_push=False,
            )
            if send_email or send_sms or send_push:
                msg.send_email = send_email
                msg.send_sms = send_sms
                msg.send_push = send_push
                msg.save(update_fields=['send_email', 'send_sms', 'send_push'])

            logger.info(
                f"Created Inbox Message ID {msg.id} for template '{template_code}' "
                f"with {len(recipients)} recipient(s)"
            )
        else:
            # No in-app message — derive a fallback subject/body for the other
            # channels from the email/SMS template fields.
            subject = self._render_template(template.email_subject or '', context_data)
            message = self._render_template(template.email_body or template.sms_body or '', context_data)

        action_url = msg.action_url if msg else ''

        # Per-channel delivery via the channel registry. Built-in email/SMS/push
        # are registered senders; extensions (e.g. PackGo WeChat) register extra
        # channels through MessageService.register_channel and are orchestrated
        # here with the same per-recipient preference semantics. ``force_*`` only
        # override the matching built-in channel; extra channels follow their
        # template_enabled flag.
        force_overrides = {'email': force_email, 'sms': force_sms, 'push': force_push}
        for channel in self.get_channels():
            force = force_overrides.get(channel.name)
            channel_on = (force if force is not None else True) and channel.template_enabled(template)
            if not channel_on:
                continue
            for recipient in recipients:
                if not channel.recipient_enabled(recipient):
                    continue
                try:
                    channel.send(self, recipient, template, context_data, subject, message, action_url)
                except Exception as e:
                    logger.error(f"Failed to send {channel.name} to {recipient.id}: {e}")

        return msg
    
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


# Register built-in channels. email/SMS/push are first-class but no longer
# special-cased in send_from_template; extensions register additional channels
# the same way (MessageService.register_channel(MyChannel())).
MessageService.register_channel(_EmailChannel())
MessageService.register_channel(_SMSChannel())
MessageService.register_channel(_PushChannel())


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

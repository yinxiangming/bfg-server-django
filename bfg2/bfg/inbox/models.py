# -*- coding: utf-8 -*-
"""
Models for BFG Inbox module.
Message and notification system with multi-channel delivery.
"""

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings


class Message(models.Model):
    """
    Message/notification sent to users.
    """
    MESSAGE_TYPE_CHOICES = (
        ('notification', _('Notification')),
        ('message', _('Direct Message')),
        ('system', _('System Message')),
        ('announcement', _('Announcement')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='messages')
    
    # Content
    subject = models.CharField(_("Subject"), max_length=255)
    message = models.TextField(_("Message"))
    message_type = models.CharField(_("Type"), max_length=20, choices=MESSAGE_TYPE_CHOICES, default='notification')
    
    # Sender
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages')
    
    # Link/Action
    action_url = models.URLField(_("Action URL"), blank=True)  # Optional link
    action_label = models.CharField(_("Action Label"), max_length=100, blank=True)
    
    # Related objects
    related_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey('related_content_type', 'related_object_id')
    
    # Delivery
    send_email = models.BooleanField(_("Send Email"), default=False)
    send_sms = models.BooleanField(_("Send SMS"), default=False)
    send_push = models.BooleanField(_("Send Push"), default=False)
    
    # Scheduling
    send_email_at = models.DateTimeField(_("Send Email At"), null=True, blank=True)  # Schedule for later
    send_sms_at = models.DateTimeField(_("Send SMS At"), null=True, blank=True)
    send_push_at = models.DateTimeField(_("Send Push At"), null=True, blank=True)
    
    # Timestamps
    expires_at = models.DateTimeField(_("Expires At"), null=True, blank=True)
    read_at = models.DateTimeField(_("Read At"), null=True, blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
        ]
    
    def __str__(self):
        return self.subject


class MessageTemplate(models.Model):
    """
    Message template for system events.
    Supports email, app message, and SMS templates.
    """    
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, null=True, blank=True, default=None, related_name='message_templates')
    
    # Template identification
    name = models.CharField(_("Name"), max_length=100)
    code = models.CharField(_("Code"), max_length=50)  # Internal code
    event = models.CharField(_("Event"), max_length=50) # System event code
    
    # Email template
    email_enabled = models.BooleanField(_("Email Enabled"), default=False)
    email_subject = models.CharField(_("Email Subject"), max_length=255, blank=True)
    email_body = models.TextField(_("Email Body"), blank=True)  # Supports template variables
    email_html_body = models.TextField(_("Email HTML Body"), blank=True)  # HTML version
    
    # App message template
    app_message_enabled = models.BooleanField(_("App Message Enabled"), default=False)
    app_message_title = models.CharField(_("App Message Title"), max_length=255, blank=True)
    app_message_body = models.TextField(_("App Message Body"), blank=True)
    
    # SMS template
    sms_enabled = models.BooleanField(_("SMS Enabled"), default=False)
    sms_body = models.TextField(_("SMS Body"), max_length=160, blank=True)  # SMS character limit
    
    # Push notification template
    push_enabled = models.BooleanField(_("Push Enabled"), default=False)
    push_title = models.CharField(_("Push Title"), max_length=100, blank=True)
    push_body = models.CharField(_("Push Body"), max_length=255, blank=True)
    
    # Template variables guide
    available_variables = models.JSONField(_("Available Variables"), default=dict, blank=True)
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    # Settings
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Message Template")
        verbose_name_plural = _("Message Templates")
        unique_together = ('workspace', 'code', 'language')
        ordering = ['name']
    
    def __str__(self):
        return self.name


class MessageRecipient(models.Model):
    """
    Message recipient with read status tracking.
    """
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='recipients')
    recipient = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='received_messages')
    
    # Status
    is_read = models.BooleanField(_("Read"), default=False)
    is_archived = models.BooleanField(_("Archived"), default=False)
    is_deleted = models.BooleanField(_("Deleted"), default=False)
    
    # Timestamps
    delivered_at = models.DateTimeField(_("Delivered At"), default=timezone.now)
    read_at = models.DateTimeField(_("Read At"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("Message Recipient")
        verbose_name_plural = _("Message Recipients")
        unique_together = ('message', 'recipient')
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'delivered_at']),
        ]
    
    def __str__(self):
        return f"{self.recipient} - {self.message.subject}"


class SMSMessage(models.Model):
    """
    SMS message sent to customers.
    """
    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('sent', _('Sent')),
        ('delivered', _('Delivered')),
        ('failed', _('Failed')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='sms_messages')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='sms_messages')
    
    # Phone
    phone_number = models.CharField(_("Phone Number"), max_length=20)
    
    # Content
    message = models.TextField(_("Message"), max_length=160)  # SMS character limit
    
    # Status
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Provider response
    provider = models.CharField(_("Provider"), max_length=50, blank=True)  # Twilio, Plivo, etc.
    provider_id = models.CharField(_("Provider ID"), max_length=100, blank=True)  # External message ID
    provider_response = models.JSONField(_("Provider Response"), default=dict, blank=True)
    
    # Related message
    message_ref = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name='sms_messages')
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    sent_at = models.DateTimeField(_("Sent At"), null=True, blank=True)
    delivered_at = models.DateTimeField(_("Delivered At"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("SMS Message")
        verbose_name_plural = _("SMS Messages")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['customer', '-created_at']),
        ]
    
    def __str__(self):
        return f"SMS to {self.phone_number}"

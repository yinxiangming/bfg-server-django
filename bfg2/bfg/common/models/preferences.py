# -*- coding: utf-8 -*-
"""
User Preferences Model
Stores user-specific settings like notification preferences, privacy settings, etc.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings


class UserPreferences(models.Model):
    """
    User preferences and personal settings.
    One-to-one relationship with User.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='preferences',
        verbose_name=_("User")
    )
    
    # Notification preferences
    email_notifications = models.BooleanField(_("Email Notifications"), default=True)
    sms_notifications = models.BooleanField(_("SMS Notifications"), default=False)
    push_notifications = models.BooleanField(_("Push Notifications"), default=True)
    
    # Notification types
    notify_order_updates = models.BooleanField(_("Order Updates"), default=True)
    notify_promotions = models.BooleanField(_("Promotions"), default=True)
    notify_product_updates = models.BooleanField(_("Product Updates"), default=False)
    notify_support_replies = models.BooleanField(_("Support Replies"), default=True)
    
    # Privacy settings
    profile_visibility = models.CharField(
        _("Profile Visibility"),
        max_length=20,
        choices=[
            ('public', _('Public')),
            ('private', _('Private')),
            ('friends', _('Friends Only')),
        ],
        default='private'
    )
    show_email = models.BooleanField(_("Show Email"), default=False)
    show_phone = models.BooleanField(_("Show Phone"), default=False)
    
    # Display preferences
    theme = models.CharField(
        _("Theme"),
        max_length=20,
        choices=[
            ('light', _('Light')),
            ('dark', _('Dark')),
            ('auto', _('Auto')),
        ],
        default='auto'
    )
    items_per_page = models.IntegerField(_("Items Per Page"), default=20)
    
    # Custom preferences (JSON field for extensibility)
    custom_preferences = models.JSONField(_("Custom Preferences"), default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("User Preferences")
        verbose_name_plural = _("User Preferences")
    
    def __str__(self):
        return f"Preferences for {self.user.username}"
    
    @classmethod
    def get_or_create_for_user(cls, user):
        """Get or create preferences for a user"""
        preferences, created = cls.objects.get_or_create(user=user)
        return preferences


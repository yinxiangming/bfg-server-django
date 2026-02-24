# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

class SubscriptionPlan(models.Model):
    """Subscription plan for recurring products."""
    INTERVAL_CHOICES = (
        ('day', _('Daily')),
        ('week', _('Weekly')),
        ('month', _('Monthly')),
        ('year', _('Yearly')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='subscription_plans')
    
    name = models.CharField(_("Name"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    
    # Pricing
    price = models.DecimalField(_("Price"), max_digits=10, decimal_places=2)
    
    # Billing
    interval = models.CharField(_("Billing Interval"), max_length=10, choices=INTERVAL_CHOICES, default='month')
    interval_count = models.PositiveIntegerField(_("Interval Count"), default=1)  # e.g., every 3 months
    
    # Trial
    trial_period_days = models.PositiveIntegerField(_("Trial Period (days)"), default=0)
    
    # Features
    features = models.JSONField(_("Features"), default=list, blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Subscription Plan")
        verbose_name_plural = _("Subscription Plans")
        ordering = ['price']
    
    def __str__(self):
        return f"{self.name} - {self.get_interval_display()}"


class Subscription(models.Model):
    """Active customer subscription."""
    STATUS_CHOICES = (
        ('active', _('Active')),
        ('trialing', _('Trialing')),
        ('past_due', _('Past Due')),
        ('cancelled', _('Cancelled')),
        ('expired', _('Expired')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='subscriptions')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Dates
    start_date = models.DateTimeField(_("Start Date"), default=timezone.now)
    end_date = models.DateTimeField(_("End Date"), null=True, blank=True)
    trial_end = models.DateTimeField(_("Trial End"), null=True, blank=True)
    next_billing_date = models.DateTimeField(_("Next Billing Date"), null=True, blank=True)
    cancelled_at = models.DateTimeField(_("Cancelled At"), null=True, blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Subscription")
        verbose_name_plural = _("Subscriptions")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'customer']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.customer} - {self.plan.name}"

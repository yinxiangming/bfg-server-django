# -*- coding: utf-8 -*-
"""
Customer Segmentation models for BFG Common module.
Allows grouping customers based on criteria and tagging them.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation

class Customer(models.Model):
    """
    Customer profile linking User to Workspace.
    A user can be a customer of multiple workspaces.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='customers', verbose_name=_("Workspace"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_profiles',
        verbose_name=_("User")
    )
    
    # Customer-specific info
    customer_number = models.CharField(_("Customer Number"), max_length=50, blank=True)
    
    # Business info
    company_name = models.CharField(_("Company Name"), max_length=255, blank=True)
    tax_number = models.CharField(_("Tax Number"), max_length=100, blank=True)
    
    # Financial
    credit_limit = models.DecimalField(_("Credit Limit"), max_digits=10, decimal_places=2, default=0)
    balance = models.DecimalField(_("Balance"), max_digits=10, decimal_places=2, default=0)
    
    # Status
    is_active = models.BooleanField(_("Active"), default=True)
    is_verified = models.BooleanField(_("Verified"), default=False)
    verified_at = models.DateTimeField(_("Verified At"), null=True, blank=True)
    
    # Notes
    notes = models.TextField(_("Notes"), blank=True)
    
    # Payment gateway metadata (stores stripe_customer_id, etc.)
    gateway_metadata = models.JSONField(_("Gateway Metadata"), default=dict, blank=True)
    
    # Addresses (reverse relation)
    addresses = GenericRelation('common.Address', related_query_name='customer')
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Customer")
        verbose_name_plural = _("Customers")
        unique_together = [
            ('workspace', 'user'),
            ('workspace', 'customer_number'),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.get_full_name()} ({self.workspace.name})"


class CustomerSegment(models.Model):
    """
    Dynamic customer segment based on rules.
    e.g., "VIP Customers" (spent > $1000), "New Customers" (joined < 30 days ago).
    """
    workspace = models.ForeignKey(
        'common.Workspace', 
        on_delete=models.CASCADE, 
        related_name='customer_segments'
    )
    
    name = models.CharField(_("Name"), max_length=255)
    
    # Filter query/rules
    # e.g., {"total_spent": {"gt": 1000}, "orders_count": {"gt": 5}}
    query = models.JSONField(_("Query Rules"), default=dict)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Customer Segment")
        verbose_name_plural = _("Customer Segments")
        ordering = ['name']
        unique_together = ('workspace', 'name')
    
    def __str__(self):
        return self.name


class CustomerTag(models.Model):
    """
    Tag for manual customer organization.
    """
    workspace = models.ForeignKey(
        'common.Workspace', 
        on_delete=models.CASCADE, 
        related_name='customer_tags'
    )
    
    name = models.CharField(_("Name"), max_length=50)
    
    # Customers with this tag
    customers = models.ManyToManyField(
        'common.Customer', 
        related_name='tags', 
        blank=True
    )
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Customer Tag")
        verbose_name_plural = _("Customer Tags")
        ordering = ['name']
        unique_together = ('workspace', 'name')
    
    def __str__(self):
        return self.name

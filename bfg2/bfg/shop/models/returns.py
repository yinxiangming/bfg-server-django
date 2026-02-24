# -*- coding: utf-8 -*-
"""
Return management models for BFG Shop module.
Handles Return Merchandise Authorization (RMA) and return processing.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings

class Return(models.Model):
    """
    Return Merchandise Authorization (RMA) request.
    """
    STATUS_CHOICES = (
        ('open', _('Open')),
        ('approved', _('Approved')),
        ('rejected', _('Rejected')),
        ('received', _('Received')),
        ('inspected', _('Inspected')),
        ('refunded', _('Refunded')),
        ('closed', _('Closed')),
        ('cancelled', _('Cancelled')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='returns')
    order = models.ForeignKey('shop.Order', on_delete=models.CASCADE, related_name='returns')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='returns')
    
    return_number = models.CharField(_("Return Number"), max_length=50, unique=True)
    
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='open')
    
    # Optional link to refund if processed
    refund = models.ForeignKey(
        'finance.Refund', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='return_request'
    )
    
    # Notes
    reason_category = models.CharField(_("Reason Category"), max_length=50, blank=True)
    customer_note = models.TextField(_("Customer Note"), blank=True)
    admin_note = models.TextField(_("Admin Note"), blank=True)
    
    # Dates
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    closed_at = models.DateTimeField(_("Closed At"), null=True, blank=True)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='returns_created'
    )
    
    class Meta:
        verbose_name = _("Return")
        verbose_name_plural = _("Returns")
        ordering = ['-created_at']
        unique_together = ('workspace', 'return_number')
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['order']),
        ]
    
    def __str__(self):
        return self.return_number


class ReturnLineItem(models.Model):
    """
    Specific items being returned in a Return request.
    """
    RESTOCK_ACTION_CHOICES = (
        ('no_restock', _('No Restock')),
        ('restock', _('Restock')),
        ('damage', _('Damaged/Dispose')),
    )
    
    return_request = models.ForeignKey(Return, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey('shop.OrderItem', on_delete=models.CASCADE, related_name='return_items')
    
    quantity = models.PositiveIntegerField(_("Quantity"))
    
    reason = models.CharField(_("Reason"), max_length=255, blank=True)
    
    # Processing
    restock_action = models.CharField(
        _("Restock Action"), 
        max_length=20, 
        choices=RESTOCK_ACTION_CHOICES, 
        default='no_restock'
    )
    
    class Meta:
        verbose_name = _("Return Line Item")
        verbose_name_plural = _("Return Line Items")
    
    def __str__(self):
        return f"{self.return_request.return_number} - {self.order_item.product_name} x {self.quantity}"

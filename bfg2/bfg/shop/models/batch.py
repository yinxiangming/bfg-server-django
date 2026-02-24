# -*- coding: utf-8 -*-
"""
Optional Batch Management Models for BFG Shop module.

This is an advanced feature for shops that need lot/batch tracking and expiry management.
Enable it by setting ENABLE_BATCH_MANAGEMENT = True in workspace settings.

Use cases:
- Food products with expiry dates
- Pharmaceuticals requiring lot tracking
- Products requiring recall capabilities
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from datetime import timedelta


class ProductBatch(models.Model):
    """
    Product batch/lot for inventory tracking
    
    Tracks specific batches with manufacturing and expiry dates.
    Supports FIFO (First-In-First-Out) inventory management.
    """
    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='product_batches'
    )
    variant = models.ForeignKey(
        'ProductVariant',
        on_delete=models.CASCADE,
        related_name='batches'
    )
    warehouse = models.ForeignKey(
        'delivery.Warehouse',
        on_delete=models.CASCADE,
        related_name='product_batches'
    )
    
    # Batch identification
    batch_number = models.CharField(
        _("Batch Number"),
        max_length=100,
        help_text=_("Unique batch/lot number")
    )
    
    # Dates
    manufactured_date = models.DateField(_("Manufactured Date"))
    expiry_date = models.DateField(
        _("Expiry Date"),
        null=True,
        blank=True,
        help_text=_("Leave blank if product doesn't expire")
    )
    
    # Stock levels
    quantity = models.IntegerField(_("Quantity"), default=0)
    reserved = models.IntegerField(
        _("Reserved Quantity"),
        default=0,
        help_text=_("Quantity reserved for orders")
    )
    
    # Cost tracking
    purchase_price = models.DecimalField(
        _("Purchase Price"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    # Quality status
    QUALITY_STATUS_CHOICES = [
        ('normal', _('Normal')),
        ('warning', _('Near Expiry')),
        ('expired', _('Expired')),
        ('recalled', _('Recalled')),
        ('quarantine', _('Quarantine')),
    ]
    quality_status = models.CharField(
        _("Quality Status"),
        max_length=20,
        choices=QUALITY_STATUS_CHOICES,
        default='normal'
    )
    
    # Notes
    notes = models.TextField(_("Notes"), blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Product Batch")
        verbose_name_plural = _("Product Batches")
        unique_together = ('workspace', 'batch_number', 'warehouse')
        ordering = ['expiry_date', 'manufactured_date']  # FIFO ordering
        indexes = [
            models.Index(fields=['workspace', 'variant', 'warehouse']),
            models.Index(fields=['expiry_date']),
            models.Index(fields=['quality_status']),
        ]
    
    def __str__(self):
        return f"{self.batch_number} - {self.variant}"
    
    @property
    def available(self) -> int:
        """Available quantity (not reserved)"""
        return max(0, self.quantity - self.reserved)
    
    @property
    def days_to_expiry(self) -> int:
        """Days until expiry (None if no expiry date)"""
        if not self.expiry_date:
            return None
        delta = self.expiry_date - timezone.now().date()
        return delta.days
    
    @property
    def is_near_expiry(self) -> bool:
        """Is batch near expiry (within 30 days)"""
        days = self.days_to_expiry
        return days is not None and 0 <= days <= 30
    
    @property
    def is_expired(self) -> bool:
        """Is batch expired"""
        days = self.days_to_expiry
        return days is not None and days < 0


class BatchMovement(models.Model):
    """
    Batch inventory movement record
    
    Tracks all stock movements for audit trail
    """
    MOVEMENT_TYPE_CHOICES = [
        ('in', _('Stock In')),
        ('out', _('Stock Out')),
        ('transfer', _('Transfer')),
        ('adjustment', _('Adjustment')),
        ('return', _('Return')),
    ]
    
    batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    
    movement_type = models.CharField(
        _("Movement Type"),
        max_length=20,
        choices=MOVEMENT_TYPE_CHOICES
    )
    quantity = models.IntegerField(
        _("Quantity"),
        help_text=_("Positive for increase, negative for decrease")
    )
    
    # Related records
    order = models.ForeignKey(
        'Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batch_movements'
    )
    consignment = models.ForeignKey(
        'delivery.Consignment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batch_movements'
    )
    
    # Details
    reason = models.CharField(_("Reason"), max_length=255, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='batch_movements'
    )
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Batch Movement")
        verbose_name_plural = _("Batch Movements")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['batch', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.movement_type} - {self.quantity} ({self.batch.batch_number})"

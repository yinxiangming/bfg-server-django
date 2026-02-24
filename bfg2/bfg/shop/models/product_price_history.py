# -*- coding: utf-8 -*-
"""
Product Price History model for scheduled price changes.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings


class ProductPriceHistory(models.Model):
    """
    Product price history and scheduled price changes.
    Allows tracking price changes and scheduling future price updates.
    """
    
    STATUS_CHOICES = [
        ('pending', _('Pending')),      # Scheduled but not yet effective
        ('active', _('Active')),        # Currently in effect
        ('cancelled', _('Cancelled')),  # Cancelled before taking effect
    ]
    
    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='product_price_history'
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='price_history'
    )
    
    # Price information
    old_price = models.DecimalField(
        _('Old Price'),
        max_digits=10,
        decimal_places=2
    )
    new_price = models.DecimalField(
        _('New Price'),
        max_digits=10,
        decimal_places=2
    )
    
    # Effective time
    effective_at = models.DateTimeField(
        _('Effective At'),
        help_text='When this price change takes effect. Allows scheduling future price changes.'
    )
    
    # Audit
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='price_changes'
    )
    changed_at = models.DateTimeField(_('Changed At'), auto_now_add=True)
    reason = models.TextField(_('Reason'), blank=True, help_text='Reason for price change')
    
    # Status
    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    class Meta:
        verbose_name = _('Product Price History')
        verbose_name_plural = _('Product Price History')
        ordering = ['-effective_at']
        indexes = [
            models.Index(fields=['product', '-effective_at']),
            models.Index(fields=['status', 'effective_at']),
        ]
    
    def __str__(self):
        return f"{self.product.name}: {self.old_price} → {self.new_price} @ {self.effective_at}"

# -*- coding: utf-8 -*-
"""
Gift Card models for BFG Marketing module.
Digital gift cards with balance tracking.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
import secrets


class GiftCard(models.Model):
    """
    Prepaid gift card with a balance.
    Can be issued to a specific customer or generic (bearer token).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='gift_cards')

    # Code should be hashed in production, but storing plain for MVP/Demo
    code = models.CharField(_("Code"), max_length=50, unique=True)

    initial_value = models.DecimalField(_("Initial Value"), max_digits=10, decimal_places=2)
    balance = models.DecimalField(_("Current Balance"), max_digits=10, decimal_places=2)
    currency = models.ForeignKey('finance.Currency', on_delete=models.PROTECT)

    # Optional owner
    customer = models.ForeignKey(
        'common.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gift_cards'
    )

    # Status
    is_active = models.BooleanField(_("Active"), default=True)
    expires_at = models.DateField(_("Expires At"), null=True, blank=True)

    # Metadata
    note = models.TextField(_("Note"), blank=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Gift Card")
        verbose_name_plural = _("Gift Cards")
        ordering = ['-created_at']
        unique_together = ('workspace', 'code')

    def __str__(self):
        return f"**** {self.code[-4:]} ({self.balance} {self.currency.code})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        if self.balance is None:
            self.balance = self.initial_value
        super().save(*args, **kwargs)

    def _generate_code(self):
        return secrets.token_hex(8).upper()

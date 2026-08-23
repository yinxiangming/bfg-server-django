# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class StockNotification(models.Model):
    """
    A visitor asking to be told when a sold-out product comes back.

    Only collected when the workspace's out-of-stock policy is ``notify``. Keyed by email
    rather than customer: the whole point is to capture demand from someone who could not
    complete a purchase, and requiring an account first would lose most of them.

    ``variant`` is null for a product with no variants, so uniqueness is enforced by two
    partial constraints instead of ``unique_together`` — NULL never equals NULL in SQL,
    which would let one address register for the same product without limit.
    """
    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='stock_notifications'
    )
    product = models.ForeignKey(
        'shop.Product',
        on_delete=models.CASCADE,
        related_name='stock_notifications'
    )
    variant = models.ForeignKey(
        'shop.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='stock_notifications'
    )
    email = models.EmailField(_("Email"))
    # Set when the visitor was signed in, purely so the back office can tell a known
    # customer's request from an anonymous one. Never used to look the address up.
    customer = models.ForeignKey(
        'common.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_notifications'
    )
    is_notified = models.BooleanField(_("Notified"), default=False)
    notified_at = models.DateTimeField(_("Notified At"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Stock Notification")
        verbose_name_plural = _("Stock Notifications")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'product', 'is_notified']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'product', 'variant', 'email'],
                condition=models.Q(variant__isnull=False),
                name='uniq_stock_notification_variant',
            ),
            models.UniqueConstraint(
                fields=['workspace', 'product', 'email'],
                condition=models.Q(variant__isnull=True),
                name='uniq_stock_notification_product',
            ),
        ]

    def __str__(self):
        return f"{self.email} - {self.product.name}"

# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class Wishlist(models.Model):
    """Customer wishlist: favorited products per workspace/customer."""
    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='wishlists'
    )
    customer = models.ForeignKey(
        'common.Customer',
        on_delete=models.CASCADE,
        related_name='wishlists'
    )
    product = models.ForeignKey(
        'shop.Product',
        on_delete=models.CASCADE,
        related_name='wishlist_entries'
    )
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Wishlist")
        verbose_name_plural = _("Wishlists")
        ordering = ['-created_at']
        unique_together = ('workspace', 'customer', 'product')

    def __str__(self):
        return f"{self.customer} - {self.product.name}"

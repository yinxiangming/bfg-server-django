# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

class Cart(models.Model):
    """Shopping cart for customers (authenticated or anonymous)."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='carts')
    
    # Customer (null for anonymous/guest carts)
    customer = models.ForeignKey(
        'common.Customer',
        on_delete=models.CASCADE,
        related_name='carts',
        null=True,
        blank=True,
        verbose_name=_("Customer")
    )
    
    # Session key for anonymous carts
    session_key = models.CharField(_("Session Key"), max_length=255, blank=True, db_index=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Cart")
        verbose_name_plural = _("Carts")
        ordering = ['-updated_at']
    
    def __str__(self):
        if self.customer:
            return f"Cart for {self.customer}"
        return f"Guest Cart {self.session_key[:10] if self.session_key else self.id}"
    
    @property
    def total(self):
        """Calculate cart total."""
        return sum(item.subtotal for item in self.items.all())


class CartItem(models.Model):
    """Shopping cart item."""
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('shop.Product', on_delete=models.CASCADE)
    variant = models.ForeignKey('shop.ProductVariant', null=True, blank=True, on_delete=models.CASCADE)
    
    quantity = models.PositiveIntegerField(_("Quantity"), default=1)
    price = models.DecimalField(_("Price"), max_digits=10, decimal_places=2)  # Price at time of adding
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Cart Item")
        verbose_name_plural = _("Cart Items")
    
    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    @property
    def subtotal(self):
        """Calculate item subtotal."""
        return self.price * self.quantity

# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal

class Order(models.Model):
    """Customer order."""
    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('shipped', _('Shipped')),
        ('delivered', _('Delivered')),
        ('cancelled', _('Cancelled')),
        ('refunded', _('Refunded')),
    )
    
    PAYMENT_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('paid', _('Paid')),
        ('failed', _('Failed')),
        ('refunded', _('Refunded')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='orders')
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT, related_name='orders')
    store = models.ForeignKey('shop.Store', on_delete=models.PROTECT, related_name='orders')
    sales_channel = models.ForeignKey(
        'shop.SalesChannel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text="Sales channel where the order was placed"
    )
    
    coupon = models.ForeignKey(
        'marketing.Coupon',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text=_("Coupon used for this order")
    )
    
    freight_service = models.ForeignKey(
        'delivery.FreightService',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text=_("Freight service used for shipping this order")
    )
    
    # Order Info
    order_number = models.CharField(_("Order Number"), max_length=50, unique=True)
    
    # Status
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(_("Payment Status"), max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    
    # Amounts
    subtotal = models.DecimalField(_("Subtotal"), max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(_("Shipping Cost"), max_digits=10, decimal_places=2, default=Decimal('0'))
    tax = models.DecimalField(_("Tax"), max_digits=10, decimal_places=2, default=Decimal('0'))
    discount = models.DecimalField(_("Discount"), max_digits=10, decimal_places=2, default=Decimal('0'))
    total = models.DecimalField(_("Total"), max_digits=10, decimal_places=2)
    
    # Addresses
    shipping_address = models.ForeignKey('common.Address', on_delete=models.PROTECT, related_name='shipping_orders')
    billing_address = models.ForeignKey('common.Address', on_delete=models.PROTECT, related_name='billing_orders')
    
    # Notes
    customer_note = models.TextField(_("Customer Note"), blank=True)
    admin_note = models.TextField(_("Admin Note"), blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    paid_at = models.DateTimeField(_("Paid At"), null=True, blank=True)
    shipped_at = models.DateTimeField(_("Shipped At"), null=True, blank=True)
    delivered_at = models.DateTimeField(_("Delivered At"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['store', '-created_at']),
            models.Index(fields=['order_number']),
            models.Index(fields=['status']),
            models.Index(fields=['sales_channel']),
        ]
    
    def __str__(self):
        return f"Order {self.order_number}"


class OrderItem(models.Model):
    """Order line item."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('shop.Product', on_delete=models.PROTECT)
    variant = models.ForeignKey('shop.ProductVariant', null=True, blank=True, on_delete=models.PROTECT)
    
    # Product snapshot at time of order
    product_name = models.CharField(_("Product Name"), max_length=255)
    variant_name = models.CharField(_("Variant Name"), max_length=255, blank=True)
    sku = models.CharField(_("SKU"), max_length=100, blank=True)
    
    quantity = models.PositiveIntegerField(_("Quantity"))
    price = models.DecimalField(_("Price"), max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(_("Subtotal"), max_digits=10, decimal_places=2)
    
    class Meta:
        verbose_name = _("Order Item")
        verbose_name_plural = _("Order Items")
    
    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

# -*- coding: utf-8 -*-
from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
import os

class ProductTag(models.Model):
    """Product tag for flexible organization."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='product_tags')
    
    name = models.CharField(_("Name"), max_length=50)
    slug = models.SlugField(_("Slug"), max_length=50)
    
    language = models.CharField(_("Language"), max_length=10)
    
    class Meta:
        verbose_name = _("Product Tag")
        verbose_name_plural = _("Product Tags")
        ordering = ['name']
        unique_together = ('workspace', 'slug', 'language')
    
    def __str__(self):
        return self.name


class Product(models.Model):
    """Product catalog item (both one-time and subscription)."""
    PRODUCT_TYPE_CHOICES = (
        ('physical', _('Physical Product')),
        ('digital', _('Digital Product')),
        ('service', _('Service')),
        ('subscription', _('Subscription')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='products')
    
    # Basic Info
    name = models.CharField(_("Name"), max_length=255)
    slug = models.SlugField(_("Slug"), max_length=255)
    sku = models.CharField(_("SKU"), max_length=100, blank=True)
    barcode = models.CharField(_("Barcode"), max_length=100, blank=True)
    
    # Type
    product_type = models.CharField(_("Product Type"), max_length=20, choices=PRODUCT_TYPE_CHOICES, default='physical')
    
    # Content
    description = models.TextField(_("Description"), blank=True)
    short_description = models.CharField(_("Short Description"), max_length=255, blank=True)
    
    # Pricing
    price = models.DecimalField(_("Price"), max_digits=10, decimal_places=2)
    compare_price = models.DecimalField(_("Compare Price"), max_digits=10, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(_("Cost"), max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Subscription (if product_type='subscription')
    is_subscription = models.BooleanField(_("Is Subscription"), default=False)
    subscription_plan = models.ForeignKey('shop.SubscriptionPlan', null=True, blank=True, on_delete=models.SET_NULL, related_name='products')
    
    # Organization
    categories = models.ManyToManyField('shop.ProductCategory', blank=True, related_name='products')
    tags = models.ManyToManyField(ProductTag, blank=True, related_name='products')
    
    # Finance
    finance_code = models.ForeignKey(
        'finance.FinancialCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name=_("Finance Code"),
        help_text=_("Default financial code for invoicing this product")
    )
    
    # Inventory
    track_inventory = models.BooleanField(_("Track Inventory"), default=True)
    stock_quantity = models.IntegerField(_("Stock Quantity"), default=0)
    low_stock_threshold = models.IntegerField(_("Low Stock Threshold"), default=10)
    
    # Shipping
    requires_shipping = models.BooleanField(_("Requires Shipping"), default=True)
    weight = models.DecimalField(_("Weight (kg)"), max_digits=10, decimal_places=2, null=True, blank=True)
    
    # SEO
    meta_title = models.CharField(_("Meta Title"), max_length=255, blank=True)
    meta_description = models.TextField(_("Meta Description"), blank=True)
    
    # Status
    is_active = models.BooleanField(_("Active"), default=True)
    is_featured = models.BooleanField(_("Featured"), default=False)
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    # Generic relation to MediaLink (replaces ProductMedia)
    media_links = GenericRelation('common.MediaLink', related_query_name='product')
    
    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        ordering = ['-created_at']
        unique_together = ('workspace', 'slug', 'language')
        indexes = [
            models.Index(fields=['workspace', 'slug']),
            models.Index(fields=['workspace', 'is_active']),
            models.Index(fields=['sku']),
        ]
    
    def __str__(self):
        return self.name

    @property
    def primary_image(self):
        """Get primary image from media_links."""
        from django.contrib.contenttypes.models import ContentType
        content_type = ContentType.objects.get_for_model(self.__class__)
        return self.media_links.filter(media__media_type='image').select_related('media').order_by('position').first()


class ProductVariant(models.Model):
    """Product variant (size, color, etc.)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    
    # Variant Info
    sku = models.CharField(_("SKU"), max_length=100)
    name = models.CharField(_("Variant Name"), max_length=255)
    
    # Options (e.g., {"size": "Large", "color": "Red"})
    options = models.JSONField(_("Options"), default=dict)
    
    # Pricing
    price = models.DecimalField(_("Price"), max_digits=10, decimal_places=2, null=True, blank=True)
    compare_price = models.DecimalField(_("Compare Price"), max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Inventory
    stock_quantity = models.IntegerField(_("Stock Quantity"), default=0)
    
    # Physical
    weight = models.DecimalField(_("Weight (kg)"), max_digits=10, decimal_places=2, null=True, blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    
    class Meta:
        verbose_name = _("Product Variant")
        verbose_name_plural = _("Product Variants")
        ordering = ['order', 'name']
        unique_together = ('product', 'sku')
    
    def __str__(self):
        return f"{self.product.name} - {self.name}"


class VariantInventory(models.Model):
    """Inventory tracking per warehouse for product variants."""
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='inventory')
    warehouse = models.ForeignKey('delivery.Warehouse', on_delete=models.CASCADE, related_name='variant_inventory')
    
    quantity = models.IntegerField(_("Quantity"), default=0)
    reserved = models.IntegerField(_("Reserved"), default=0)  # Reserved for orders
    
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Variant Inventory")
        verbose_name_plural = _("Variant Inventories")
        unique_together = ('variant', 'warehouse')
    
    def __str__(self):
        return f"{self.variant} @ {self.warehouse} - {self.quantity}"
    
    @property
    def available(self):
        """Available quantity (not reserved)."""
        return self.quantity - self.reserved


# ProductMedia model removed - use common.MediaLink with GenericForeignKey instead

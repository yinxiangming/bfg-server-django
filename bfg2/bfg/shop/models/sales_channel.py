# -*- coding: utf-8 -*-
"""
Sales Channel models for BFG Shop module.
Manages where products are sold (Online Store, POS, Mobile App, etc.).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

class SalesChannel(models.Model):
    """
    A sales channel where products are sold.
    Examples: Online Store, POS, Mobile App, Facebook, Instagram.
    """
    CHANNEL_TYPE_CHOICES = (
        ('online_store', _('Online Store')),
        ('pos', _('Point of Sale')),
        ('mobile_app', _('Mobile App')),
        ('social', _('Social Media')),
        ('marketplace', _('Marketplace')),
        ('custom', _('Custom')),
    )

    workspace = models.ForeignKey(
        'common.Workspace', 
        on_delete=models.CASCADE, 
        related_name='sales_channels'
    )
    
    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    channel_type = models.CharField(
        _("Channel Type"), 
        max_length=20, 
        choices=CHANNEL_TYPE_CHOICES,
        default='custom'
    )
    description = models.TextField(_("Description"), blank=True)
    
    # Configuration
    config = models.JSONField(_("Configuration"), default=dict, blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    is_default = models.BooleanField(_("Default"), default=False)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Sales Channel")
        verbose_name_plural = _("Sales Channels")
        ordering = ['name']
        unique_together = ('workspace', 'code')
    
    def __str__(self):
        return self.name


class ProductChannelListing(models.Model):
    """
    Controls visibility of a product on a specific sales channel.
    If a record exists, the product is available on that channel.
    """
    product = models.ForeignKey(
        'shop.Product', 
        on_delete=models.CASCADE, 
        related_name='channel_listings'
    )
    channel = models.ForeignKey(
        SalesChannel, 
        on_delete=models.CASCADE, 
        related_name='product_listings'
    )
    
    # Channel specific overrides (optional)
    available_at = models.DateTimeField(_("Available At"), null=True, blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Product Channel Listing")
        verbose_name_plural = _("Product Channel Listings")
        unique_together = ('product', 'channel')
    
    def __str__(self):
        return f"{self.product.name} on {self.channel.name}"


class ChannelCollection(models.Model):
    """
    Controls visibility of a collection/category on a specific sales channel.
    """
    category = models.ForeignKey(
        'shop.ProductCategory', 
        on_delete=models.CASCADE, 
        related_name='channel_listings'
    )
    channel = models.ForeignKey(
        SalesChannel, 
        on_delete=models.CASCADE, 
        related_name='collection_listings'
    )
    
    available_at = models.DateTimeField(_("Available At"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Channel Collection")
        verbose_name_plural = _("Channel Collections")
        unique_together = ('category', 'channel')
    
    def __str__(self):
        return f"{self.category.name} on {self.channel.name}"

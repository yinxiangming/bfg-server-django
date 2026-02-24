# -*- coding: utf-8 -*-
from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

class Store(models.Model):
    """Store (physical or online) belonging to a workspace."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='stores')
    
    # Basic Info
    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)
    
    # Warehouses (0 or more per store)
    warehouses = models.ManyToManyField('delivery.Warehouse', blank=True, related_name='stores')
    
    # Addresses (reverse relation - a store can have multiple addresses)
    addresses = GenericRelation('common.Address', related_query_name='store')
    
    # Settings
    settings = models.JSONField(_("Settings"), default=dict, blank=True)
    
    # Status
    is_active = models.BooleanField(_("Active"), default=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Store")
        verbose_name_plural = _("Stores")
        ordering = ['name']
        unique_together = ('workspace', 'code')
        indexes = [
            models.Index(fields=['workspace', 'is_active']),
        ]
    
    def __str__(self):
        return self.name

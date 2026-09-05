# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _

from bfg.common.managers import TenantScopedModel


class ProductCategory(TenantScopedModel):
    """Product category with hierarchy support."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='product_categories')
    
    name = models.CharField(_("Name"), max_length=100)
    slug = models.SlugField(_("Slug"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    
    # Display
    icon = models.CharField(_("Icon"), max_length=50, blank=True)
    image = models.ImageField(_("Image"), upload_to='categories/', blank=True)
    
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)
    
    # Smart Collection Rules
    # e.g., [{"column": "price", "relation": "greater_than", "condition": "100"}]
    rules = models.JSONField(_("Rules"), default=list, blank=True)
    rule_match_type = models.CharField(
        _("Match Type"), 
        max_length=10, 
        choices=[('all', _('All Conditions')), ('any', _('Any Condition'))],
        default='all'
    )
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    class Meta:
        verbose_name = _("Product Category")
        verbose_name_plural = _("Product Categories")
        ordering = ['order', 'name']
        unique_together = ('workspace', 'slug', 'language')
        # Phase-0 PR-05: keep reverse FK / migration access unscoped.
        base_manager_name = 'all_objects'
    
    def __str__(self):
        return self.name

    def get_descendant_ids(self, include_self=True):
        """IDs of this category and everything below it in the tree.

        Plain-Python breadth-first walk rather than a recursive CTE: there is no
        MPTT/closure-table here, only a `parent` FK, and a workspace's category tree
        is small enough (tens of rows) that a query per level is cheap and simple.
        """
        ids = [self.pk] if include_self else []
        frontier = [self.pk]
        while frontier:
            frontier = list(
                ProductCategory.all_objects.filter(parent_id__in=frontier).values_list('pk', flat=True)
            )
            ids.extend(frontier)
        return ids

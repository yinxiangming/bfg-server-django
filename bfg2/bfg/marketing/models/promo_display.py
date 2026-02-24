# -*- coding: utf-8 -*-
"""
Campaign display models for homepage and promo blocks.
A display can be linked to a campaign (optional) and has display_type: slide, category_entry, featured.
Product/category selection uses a rules JSON list (same concept as ProductCategoryRule).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from .base import Campaign


class CampaignDisplay(models.Model):
    """Unified display block: slide, category_entry, featured. Campaign is optional."""
    DISPLAY_TYPE_CHOICES = (
        ('slide', _('Slide')),
        ('category_entry', _('Category Entry')),
        ('featured', _('Featured')),
    )

    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='campaign_displays',
        null=True,
        blank=True,
        help_text=_('Required when campaign is not set; otherwise derived from campaign.'),
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='displays',
        null=True,
        blank=True,
    )
    display_type = models.CharField(_("Display Type"), max_length=30, choices=DISPLAY_TYPE_CHOICES)
    order = models.PositiveSmallIntegerField(_("Order"), default=0)

    title = models.CharField(_("Title"), max_length=255, blank=True)
    subtitle = models.CharField(_("Subtitle"), max_length=255, blank=True)

    image = models.ImageField(_("Image"), upload_to='promo/display/', blank=True, null=True)
    link_url = models.CharField(_("Link URL"), max_length=500, blank=True)  # absolute URL or path e.g. /category/bag
    link_target = models.CharField(_("Link Target"), max_length=10, blank=True)  # _blank / _self

    # Product selection: same schema as ProductCategory.rules (CategoryRuleModel: column, relation, condition).
    # Use bfg.shop.schemas.apply_rules_to_product_queryset to filter products with one shared logic.
    rules = models.JSONField(
        _("Rules"),
        default=list,
        blank=True,
        help_text=_('Same as ProductCategory.rules: [{"column":"price","relation":"greater_than","condition":"100"}, {"column":"category_id","relation":"equals","condition":"5"}]'),
    )

    post = models.ForeignKey(
        'web.Post',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Campaign Display")
        verbose_name_plural = _("Campaign Displays")
        ordering = ['order', 'id']

    def __str__(self):
        if self.campaign_id:
            return f"{self.get_display_type_display()} for {self.campaign.name}"
        return f"{self.get_display_type_display()} (#{self.pk})"

# -*- coding: utf-8 -*-
"""
Signals for marketing app. Invalidate home page rendered cache when CampaignDisplay
or Campaign changes so storefront shows up-to-date promo (slides, category_entry, featured) data.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from bfg.marketing.models import Campaign, CampaignDisplay


def _get_workspace_id_from_display(instance):
    """Get workspace_id from CampaignDisplay (campaign or direct workspace)."""
    if instance.workspace_id:
        return instance.workspace_id
    if instance.campaign_id:
        return instance.campaign.workspace_id
    return None


def _invalidate_home_cache(workspace_id):
    if workspace_id:
        try:
            from bfg.web.services.page_service import invalidate_home_page_cache_for_workspace
            invalidate_home_page_cache_for_workspace(workspace_id)
        except ImportError:
            pass


@receiver(post_save, sender=CampaignDisplay)
def invalidate_home_cache_on_display_save(sender, instance, **kwargs):
    _invalidate_home_cache(_get_workspace_id_from_display(instance))


@receiver(post_delete, sender=CampaignDisplay)
def invalidate_home_cache_on_display_delete(sender, instance, **kwargs):
    _invalidate_home_cache(_get_workspace_id_from_display(instance))


@receiver(post_save, sender=Campaign)
def invalidate_home_cache_on_campaign_save(sender, instance, **kwargs):
    """Campaign start/end/active changes affect get_promo_available; invalidate home cache."""
    _invalidate_home_cache(instance.workspace_id)

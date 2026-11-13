"""Invalidate public CMS caches after committed editorial changes."""
from functools import partial

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from bfg.web.models import Category, Menu, MenuItem, Page, Post
from bfg.common.storefront_cache import invalidate_storefront_config_cache
from bfg.web.services.page_service import invalidate_page_rendered_cache, CACHE_INVALIDATION_LANGS


def invalidate_workspace_pages(workspace_id):
    invalidate_storefront_config_cache(workspace_id)
    pages = list(Page.objects.filter(workspace_id=workspace_id).values_list('slug', 'language'))
    languages = set(CACHE_INVALIDATION_LANGS) | {language for _, language in pages}
    for slug in {'home', *(slug for slug, _ in pages)}:
        invalidate_page_rendered_cache(workspace_id, slug, languages=list(languages))


@receiver(post_save, sender=Post)
@receiver(post_delete, sender=Post)
@receiver(post_save, sender=Page)
@receiver(post_delete, sender=Page)
@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
def content_changed(sender, instance, **kwargs):
    transaction.on_commit(partial(invalidate_workspace_pages, instance.workspace_id))


@receiver(post_save, sender=Menu)
@receiver(post_delete, sender=Menu)
@receiver(post_save, sender=MenuItem)
@receiver(post_delete, sender=MenuItem)
def navigation_changed(sender, instance, **kwargs):
    workspace_id = instance.workspace_id if isinstance(instance, Menu) else instance.menu.workspace_id
    transaction.on_commit(partial(invalidate_storefront_config_cache, workspace_id))

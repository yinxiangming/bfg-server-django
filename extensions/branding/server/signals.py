# -*- coding: utf-8 -*-
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import BrandPortalProfile
from .services import invalidate_profile_cache


def _invalidate_after_commit(instance):
    transaction.on_commit(lambda: invalidate_profile_cache(instance.workspace_id))


@receiver(post_save, sender=BrandPortalProfile)
def invalidate_profile_on_save(sender, instance, **kwargs):
    _invalidate_after_commit(instance)


@receiver(post_delete, sender=BrandPortalProfile)
def invalidate_profile_on_delete(sender, instance, **kwargs):
    _invalidate_after_commit(instance)

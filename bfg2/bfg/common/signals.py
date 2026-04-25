# -*- coding: utf-8 -*-
"""
Django signals for BFG Common module.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from .models import (
    AuditLog,
    Workspace,
    WorkspaceDomain,
    Customer,
    User,
    Settings,
    ensure_system_default_workspace_domain,
)
from bfg.core.events import global_dispatcher

import logging
logger = logging.getLogger(__name__)


@receiver(post_save, sender=Workspace)
def create_workspace_settings(sender, instance, created, **kwargs):
    """Create Settings object when a new Workspace is created and keep routing cache fresh."""
    if created:
        Settings.objects.get_or_create(workspace=instance)

    ensure_system_default_workspace_domain(instance)

    from .middleware import invalidate_workspace_cache
    invalidate_workspace_cache(instance)


@receiver(post_save, sender=WorkspaceDomain)
def invalidate_workspace_cache_on_domain_save(sender, instance, **kwargs):
    from .middleware import invalidate_workspace_cache
    invalidate_workspace_cache(instance.workspace)


@receiver(post_delete, sender=WorkspaceDomain)
def invalidate_workspace_cache_on_domain_delete(sender, instance, **kwargs):
    from .middleware import invalidate_workspace_cache
    invalidate_workspace_cache(instance.workspace)


@receiver(post_delete, sender=Workspace)
def invalidate_workspace_cache_on_delete(sender, instance, **kwargs):
    """Invalidate workspace cache when workspace is deleted."""
    from .middleware import invalidate_workspace_cache
    invalidate_workspace_cache(instance)


@receiver(post_save, sender=Customer)
def generate_customer_number(sender, instance, created, **kwargs):
    """Generate customer number if not set."""
    if created and not instance.customer_number:
        # Generate customer number: WORKSPACE_PREFIX + ID padded to 8 digits
        workspace_prefix = instance.workspace.slug[:3].upper()
        instance.customer_number = f"{workspace_prefix}{instance.id:08d}"
        instance.save(update_fields=['customer_number'])


def on_workspace_created(event_data):
    """
    Materialise every module-registered system role for a new workspace.

    Each BFG module declares its roles in ``<module>/roles.py`` and
    registers them at app-ready time. We pull the union of the
    registry here so the workspace gets ``admin`` (common),
    ``store_admin`` (shop), ``warehouse_manager`` (delivery), etc. in
    one shot.
    """
    workspace = event_data.get('data', {}).get('workspace')
    if not workspace:
        return

    try:
        from bfg.common.services.role_provisioning import provision_system_roles

        result = provision_system_roles(workspace)
        logger.info(
            "Provisioned roles for workspace %s — created=%s updated=%s skipped=%s",
            workspace.name, result.created, result.updated, result.skipped,
        )
    except Exception as e:
        logger.error(f"Failed to provision roles for workspace {workspace.id}: {e}", exc_info=True)


# Register event listener
global_dispatcher.listen('workspace.created', on_workspace_created)

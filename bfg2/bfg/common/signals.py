# -*- coding: utf-8 -*-
"""
Django signals for BFG Common module.
"""

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from .models import AuditLog, Workspace, Customer, User
from bfg.core.events import global_dispatcher

import logging
logger = logging.getLogger(__name__)

# Store old domain before save to invalidate old cache key
_workspace_old_domain = {}


@receiver(pre_save, sender=Workspace)
def store_workspace_old_domain(sender, instance, **kwargs):
    """Store old domain before save to invalidate old cache key."""
    if instance.pk:
        try:
            old_instance = Workspace.objects.get(pk=instance.pk)
            _workspace_old_domain[instance.pk] = old_instance.domain
        except Workspace.DoesNotExist:
            pass


@receiver(post_save, sender=Workspace)
def create_workspace_settings(sender, instance, created, **kwargs):
    """Create Settings object when a new Workspace is created."""
    if created:
        from .models import Settings
        Settings.objects.get_or_create(workspace=instance)
    
    # Invalidate workspace cache when domain or is_active changes
    from .middleware import invalidate_workspace_cache
    invalidate_workspace_cache(instance)
    
    # Also invalidate old domain cache if domain changed
    old_domain = _workspace_old_domain.pop(instance.pk, None)
    if old_domain and old_domain != instance.domain:
        from django.core.cache import cache
        cache.delete(f'workspace:domain:{old_domain}')


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
    Initialize basic system roles when a new workspace is created.
    Other modules will add their own roles via separate listeners.
    """
    # BaseService.emit_event wraps data in event_data['data']
    workspace = event_data.get('data', {}).get('workspace')
    if not workspace:
        return
    
    try:
        from bfg.common.utils import create_staff_roles
        
        logger.info(f"Initializing core system roles for workspace: {workspace.name}")
        
        # Only create the core admin role here
        # Other roles (store_admin, warehouse_manager, etc.) should be created
        # by their respective modules (bfg.shop, apps.wms, bfg.support)
        core_roles = [
            {
                'code': 'admin',
                'name': 'Administrator',
                'description': 'Full access to all workspace resources',
                'permissions': {'*': ['create', 'read', 'update', 'delete']},
                'is_system': True,
            },
        ]
        
        created_count = create_staff_roles(workspace, core_roles)
        logger.info(f"Created {created_count} core system role(s) for {workspace.name}")
        
    except Exception as e:
        logger.error(f"Failed to initialize core roles for workspace {workspace.id}: {e}", exc_info=True)


# Register event listener
global_dispatcher.listen('workspace.created', on_workspace_created)

# -*- coding: utf-8 -*-
"""
Custom model managers for BFG Common models.
"""

from django.db import models


def _get_current_workspace():
    """Lazy accessor for the request-scoped workspace.

    Imported at call time to avoid circular imports between
    ``bfg.common.middleware`` (which imports ``bfg.common.models``)
    and any model module that uses :class:`TenantScopedManager`.
    """
    from bfg.common.middleware import get_current_workspace
    return get_current_workspace()


class TenantScopedManager(models.Manager):
    """Default manager for models that have a ``workspace`` FK.

    Behavior:
      * ``Model.objects.all()`` is implicitly filtered to the workspace
        currently bound on the request thread by
        :class:`bfg.common.middleware.WorkspaceMiddleware`.
      * If no workspace is set (e.g. running outside a request, or the
        middleware deliberately cleared it for a public path), the
        queryset is **empty** — never the union of all tenants. This is
        a fail-closed default per Phase-0 PR-01 design.
      * Use :meth:`unscoped` (or the parallel ``all_objects`` manager
        installed by :class:`TenantScopedModel`) for migrations,
        management commands, cron jobs, or admin code that legitimately
        needs cross-tenant access.
    """

    # Bound to the abstract base via TenantScopedModel; explicit here
    # so callers using the manager directly behave identically.
    use_in_migrations = False

    def get_queryset(self):
        qs = super().get_queryset()
        workspace = _get_current_workspace()
        if workspace is None:
            return qs.none()
        return qs.filter(workspace=workspace)

    def unscoped(self):
        """Return the un-filtered queryset — bypasses tenant scoping.

        Use only when the call site is intentionally cross-tenant
        (admin tooling, data migrations, scheduled jobs).
        """
        return super().get_queryset()


class TenantScopedModel(models.Model):
    """Abstract base for any model with a ``workspace`` FK.

    Installs two managers:

    * ``objects`` — :class:`TenantScopedManager`, the safe default
      every business call site should use.
    * ``all_objects`` — vanilla ``models.Manager``, the explicit
      escape hatch for cross-tenant access.

    ``base_manager_name = "all_objects"`` ensures Django internals
    (related-object access, ``Model._base_manager``, migration helpers)
    see *all* rows — only callers reaching for ``Model.objects`` opt
    into tenant scoping.
    """

    objects = TenantScopedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"


class WorkspaceManager(models.Manager):
    """Manager for Workspace model with custom querysets."""
    
    def active(self):
        """Return only active workspaces."""
        return self.filter(is_active=True)


class CustomerManager(models.Manager):
    """Manager for Customer model with workspace filtering."""
    
    def active(self):
        """Return only active customers."""
        return self.filter(is_active=True)
    
    def verified(self):
        """Return only verified customers."""
        return self.filter(is_verified=True)
    
    def for_workspace(self, workspace):
        """Return customers for a specific workspace."""
        return self.filter(workspace=workspace)


class AddressManager(models.Manager):
    """Manager for Address model."""
    
    def shipping(self):
        """Return only shipping addresses."""
        return self.filter(address_type__in=['shipping', 'both'])
    
    def billing(self):
        """Return only billing addresses."""
        return self.filter(address_type__in=['billing', 'both'])
    
    def defaults(self):
        """Return only default addresses."""
        return self.filter(is_default=True)

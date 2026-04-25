# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings

from bfg.common.managers import TenantScopedModel


class StaffRole(models.Model):
    """
    Staff role definition for a workspace.
    Defines what permissions a staff member has.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='staff_roles', verbose_name=_("Workspace"))
    
    # Role Info
    name = models.CharField(_("Name"), max_length=100)
    code = models.CharField(_("Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)
    
    # Permissions (e.g., {"shop.view_order": True, "shop.change_order": True, ...})
    permissions = models.JSONField(_("Permissions"), default=dict, blank=True)

    # Frozen system-default permissions, captured from the role registry at
    # provisioning time. Used by "Restore defaults" — the workspace admin can
    # freely mutate ``permissions`` while ``default_permissions`` stays as
    # the module-declared baseline for that role code.
    default_permissions = models.JSONField(_("Default Permissions"), default=dict, blank=True)

    # Which module contributed this role (e.g. 'common', 'shop', 'delivery').
    # Empty for roles a workspace admin created from scratch.
    owner_module = models.CharField(_("Owner Module"), max_length=64, blank=True, default="")

    # System roles can't be deleted
    is_system = models.BooleanField(_("System Role"), default=False)
    is_active = models.BooleanField(_("Active"), default=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Staff Role")
        verbose_name_plural = _("Staff Roles")
        unique_together = ('workspace', 'code')
        ordering = ['name']
    
    def __str__(self):
        return f"{self.workspace.name} - {self.name}"


class StaffMember(TenantScopedModel):
    """
    Staff member linking a User to a Workspace with a specific role.
    Users can be staff members of multiple workspaces.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='staff_members', verbose_name=_("Workspace"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_memberships',
        verbose_name=_("User")
    )
    
    # Role
    role = models.ForeignKey(StaffRole, on_delete=models.PROTECT, related_name='staff_members', verbose_name=_("Role"))
    
    # Status
    is_active = models.BooleanField(_("Active"), default=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Staff Member")
        verbose_name_plural = _("Staff Members")
        unique_together = ('workspace', 'user')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'is_active']),
            models.Index(fields=['user', 'is_active']),
        ]
        # Phase-0 PR-08: keep reverse FK / migration access unscoped.
        base_manager_name = 'all_objects'
    
    def __str__(self):
        return f"{self.user.get_full_name()} @ {self.workspace.name} ({self.role.name})"

# -*- coding: utf-8 -*-
"""
Platform-specific permissions.

Supports embedded and standalone modes via is_embedded_mode().
"""
from rest_framework.permissions import BasePermission
from django.apps import apps

from bfg.platform.utils import is_embedded_mode, get_platform_workspace


class IsWorkspaceStaff(BasePermission):
    """Allow access only if user is a StaffMember of the requested workspace."""

    def has_object_permission(self, request, view, obj):
        workspace = getattr(obj, "workspace", obj)
        StaffMember = apps.get_model("common", "StaffMember")
        return StaffMember.objects.filter(
            user=request.user, workspace=workspace, is_active=True
        ).exists()


class IsWorkspaceOwner(BasePermission):
    """Allow access only if user is the owner (first admin) of the workspace."""

    def has_object_permission(self, request, view, obj):
        workspace = getattr(obj, "workspace", obj)
        StaffMember = apps.get_model("common", "StaffMember")
        return StaffMember.objects.filter(
            user=request.user,
            workspace=workspace,
            is_active=True,
            role__code__in=["owner", "admin"],
        ).exists()


class IsPlatformAdmin(BasePermission):
    """Allow access only to platform administrators.

    Embedded mode: user must be a StaffMember of the management Workspace.
    Standalone mode: user must be superuser or is_staff.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if is_embedded_mode():
            platform_ws = get_platform_workspace()
            if not platform_ws:
                return False
            StaffMember = apps.get_model("common", "StaffMember")
            # Platform administration is intentionally cross-workspace. The
            # request may be bound to another tenant, so the tenant-scoped
            # manager would incorrectly hide the management membership.
            return StaffMember.all_objects.filter(
                user=request.user,
                workspace=platform_ws,
                is_active=True,
            ).exists()
        else:
            return request.user.is_superuser or request.user.is_staff


class IsPlatformSuperuser(BasePermission):
    """Gate the infrastructure control plane to Django superusers only.

    Platform Workspace membership and ``is_staff`` are intentionally insufficient:
    those roles may administer a tenant, but they must never gain access to all
    tenants, cluster configuration, exports, or platform-wide billing controls.
    """

    message = "A Django superuser account is required for Platform administration."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )


class IsPlatformAPIKey(BasePermission):
    """
    Allow access via PLATFORM_API_KEY header.
    Used for internal Workspace → Platform communication (standalone mode).
    In embedded mode this permission is effectively unused (same process).
    """

    def has_permission(self, request, view):
        from django.conf import settings
        api_key = request.headers.get("X-Platform-API-Key", "")
        expected = getattr(settings, "PLATFORM_API_KEY", None)
        return bool(expected and api_key == expected)

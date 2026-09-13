# -*- coding: utf-8 -*-
"""
Platform-specific permissions.

Supports embedded and standalone modes via is_embedded_mode().
"""
from rest_framework.permissions import BasePermission
from django.apps import apps


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

    Embedded mode: user must be an active admin of the management Workspace.
    Standalone mode: user must be superuser or is_staff.

    Platform endpoints are public paths, so no workspace is bound to the
    request; the check therefore lives in ``is_platform_admin``, which looks
    memberships up without tenant scoping.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        from bfg.platform.services.workspace_service import is_platform_admin

        return is_platform_admin(request.user)


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

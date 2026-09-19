# -*- coding: utf-8 -*-
"""
Platform-specific permissions.

Supports embedded and standalone modes via is_embedded_mode().
"""
from rest_framework.permissions import BasePermission


class IsWorkspaceOwner(BasePermission):
    """Allow access only to the owner of the workspace.

    Ownership is an active owner ``PlatformMembership`` (see
    ``bfg.platform.services.ownership``), not a staff role: a workspace admin is
    not thereby its owner, and the owner need not be staff of the workspace.
    """

    # DRF sends a dict message as the response body, which is how the code
    # reaches the client next to the detail.
    message = {
        "detail": "Only the workspace owner can perform this action.",
        "code": "workspace_owner_required",
    }

    def has_object_permission(self, request, view, obj):
        from bfg.platform.services.ownership import is_workspace_owner

        workspace = getattr(obj, "workspace", obj)
        return is_workspace_owner(request.user, workspace)


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


class IsPlatformSuperuser(BasePermission):
    """Allow deployment control-plane access only to Django superusers."""

    message = {
        "detail": "Only a Django superuser can use the Platform control plane.",
        "code": "platform_superuser_required",
    }

    def has_permission(self, request, view):
        from bfg.platform.services.workspace_service import is_platform_superuser

        return is_platform_superuser(request.user)


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

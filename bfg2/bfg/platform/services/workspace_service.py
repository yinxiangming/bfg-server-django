# -*- coding: utf-8 -*-
"""
Workspace Service
Handles workspace listing and management from the Platform perspective.

Supports two modes:
  - Embedded: queries StaffMember directly (same DB)
  - Standalone: queries PlatformMembership (dedicated Platform instance)
"""
from django.conf import settings
from django.apps import apps

from bfg.common.models import resolve_workspace_public_frontend_base_url
from bfg.platform.utils import is_embedded_mode


def _safe_workspace_domain(workspace):
    if not workspace:
        return None
    try:
        return resolve_workspace_public_frontend_base_url(workspace).split('://', 1)[-1]
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_user_workspaces(user) -> list:
    """Return workspaces the user has access to."""
    if is_embedded_mode():
        return _get_user_workspaces_embedded(user)
    return _get_user_workspaces_standalone(user)


def is_platform_admin(user) -> bool:
    """Check if a user has platform admin access."""
    if is_embedded_mode():
        return _is_platform_admin_embedded(user)
    return _is_platform_admin_standalone(user)


# ── Embedded mode ─────────────────────────────────────────────────────────────

def _get_user_workspaces_embedded(user) -> list:
    """Embedded: list workspaces via StaffMember (same DB)."""
    StaffMember = apps.get_model("common", "StaffMember")
    memberships = (
        StaffMember.objects.filter(user=user, is_active=True)
        .select_related("workspace", "role")
    )

    platform_slug = getattr(settings, "PLATFORM_WORKSPACE_SLUG", "")
    result = []
    for m in memberships:
        ws = m.workspace
        result.append({
            "id": ws.id,
            "uuid": str(ws.uuid) if getattr(ws, "uuid", None) else None,
            "remote_workspace_uuid": None,
            "name": ws.name,
            "slug": ws.slug,
            "domain": _safe_workspace_domain(ws),
            "is_active": ws.is_active,
            "role": m.role.code if m.role else "staff",
            "is_platform": ws.slug == platform_slug,
            "plan": None,
            "status": "active" if ws.is_active else "suspended",
            "region": None,
            "cluster": None,
        })
    return result


def _is_platform_admin_embedded(user) -> bool:
    """Embedded: user is admin of the management Workspace."""
    from bfg.platform.utils import get_platform_workspace

    platform_ws = get_platform_workspace()
    if not platform_ws:
        return False
    StaffMember = apps.get_model("common", "StaffMember")
    return StaffMember.objects.filter(
        user=user, workspace=platform_ws, is_active=True
    ).exists()


# ── Standalone mode ───────────────────────────────────────────────────────────

def _get_user_workspaces_standalone(user) -> list:
    """Standalone: list workspaces via PlatformMembership."""
    PlatformMembership = apps.get_model("platform", "PlatformMembership")
    memberships = (
        PlatformMembership.objects.filter(user=user, is_active=True)
        .select_related(
            "profile",
            "profile__workspace",
            "profile__cluster",
        )
    )

    result = []
    for m in memberships:
        profile = m.profile
        ws = profile.workspace

        result.append({
            "id": ws.id if ws else profile.id,
            "uuid": str(ws.uuid) if ws and getattr(ws, "uuid", None) else None,
            "remote_workspace_uuid": str(profile.remote_workspace_uuid) if profile.remote_workspace_uuid else None,
            "name": ws.name if ws else None,
            "slug": ws.slug if ws else None,
            "domain": _safe_workspace_domain(ws),
            "is_active": ws.is_active if ws else not profile.is_suspended,
            "role": m.role,
            "is_platform": False,
            "plan": None,
            "status": _get_workspace_status(ws, profile),
            "region": profile.region,
            "cluster": profile.cluster.id if profile.cluster else None,
        })
    return result


def _get_workspace_status(workspace, profile) -> str:
    if workspace and not workspace.is_active:
        if profile and profile.suspended_at:
            return "suspended"
        return "inactive"
    if profile and profile.is_suspended:
        return "suspended"
    return "active"


def _is_platform_admin_standalone(user) -> bool:
    """Standalone: superuser or staff flag."""
    return getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)

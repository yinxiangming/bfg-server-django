# -*- coding: utf-8 -*-
"""
Workspace Service
Handles workspace listing and management from the Platform perspective.

Supports two modes, which differ in what makes a user a member of a workspace:
  - Embedded: an active StaffMember (same DB)
  - Standalone: an active PlatformMembership (dedicated Platform instance)

Ownership is the same in both modes; see ``bfg.platform.services.ownership``.
"""
from typing import NamedTuple, Optional

from django.apps import apps

from bfg.common.models import resolve_workspace_public_frontend_base_url
from bfg.platform.services.ownership import is_workspace_owner, owned_workspace_ids
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
    """Return the workspaces *user* is a member of or owns, with their standing in each.

    Workspaces the user is a member of come first, in membership order; those
    they own without being a member follow, by id. An owned workspace is listed
    while suspended or inactive too, so its owner can still find it.
    """
    member_roles = _member_roles(user)
    owned_ids = owned_workspace_ids(user)
    ids = list(member_roles) + [workspace_id for workspace_id in owned_ids if workspace_id not in member_roles]

    Workspace = apps.get_model("common", "Workspace")
    workspaces = Workspace.objects.select_related("platform_profile").in_bulk(ids)
    owned = set(owned_ids)
    return [
        _workspace_entry(
            workspaces[workspace_id],
            role=member_roles.get(workspace_id),
            is_member=workspace_id in member_roles,
            is_owner=workspace_id in owned,
        )
        for workspace_id in ids
        if workspace_id in workspaces
    ]


def get_user_workspace(user, workspace) -> dict:
    """*workspace* with *user*'s standing in it, as ``get_user_workspaces`` lists it.

    The standing is worked out by the same rules, so a workspace *user* has just
    created comes back exactly as ``me/`` will list it.
    """
    Workspace = apps.get_model("common", "Workspace")
    workspace = Workspace.objects.select_related("platform_profile").get(pk=workspace.pk)
    member_roles = _member_roles(user)
    return _workspace_entry(
        workspace,
        role=member_roles.get(workspace.pk),
        is_member=workspace.pk in member_roles,
        is_owner=is_workspace_owner(user, workspace),
    )


def is_platform_admin(user) -> bool:
    """Check if a user has platform admin access."""
    if is_embedded_mode():
        return _is_platform_admin_embedded(user)
    return _is_platform_admin_standalone(user)


def is_platform_superuser(user) -> bool:
    """Return whether a user can operate the deployment control plane.

    This is deliberately narrower than the historical ``is_platform_admin``
    role. Workspace-owner and shared-console access remains a tenant concern;
    cluster, lifecycle, policy, and audit controls are deployment operations
    and require Django's durable superuser flag in both embedded and standalone
    installations.
    """
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


# ── Workspace listing ─────────────────────────────────────────────────────────

class _MemberRole(NamedTuple):
    """A member's role in a workspace: its code, and the name it goes by."""
    code: Optional[str]
    name: Optional[str]


def _member_roles(user) -> dict:
    """``{workspace id: _MemberRole}`` for the workspaces *user* is an active member of.

    Embedded, membership is a StaffMember and the role is its StaffRole. This is
    a cross-workspace lookup, so it goes through ``all_objects``: the scoped
    manager only sees the workspace bound to the request, and platform endpoints
    bind none.

    Standalone, membership is a PlatformMembership, the record token exchange
    lets a user into a workspace by, and the role's name is its label. One whose
    profile has no local workspace row is left out: there is no id, name or slug
    to list it by.
    """
    if is_embedded_mode():
        StaffMember = apps.get_model("common", "StaffMember")
        rows = StaffMember.all_objects.filter(user=user, is_active=True).values_list(
            "workspace_id", "role__code", "role__name",
        )
    else:
        PlatformMembership = apps.get_model("platform", "PlatformMembership")
        labels = dict(PlatformMembership._meta.get_field("role").flatchoices)
        rows = [
            (workspace_id, code, labels.get(code, code))
            for workspace_id, code in PlatformMembership.objects.filter(
                user=user, is_active=True, profile__workspace__isnull=False,
            ).values_list("profile__workspace_id", "role")
        ]
    return {workspace_id: _MemberRole(code, name) for workspace_id, code, name in rows}


def _workspace_entry(workspace, *, role: Optional[_MemberRole], is_member, is_owner) -> dict:
    profile = getattr(workspace, "platform_profile", None)
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "created_at": workspace.created_at,
        "domain": _safe_workspace_domain(workspace),
        "status": _get_workspace_status(workspace, profile),
        "suspended_at": profile.suspended_at if profile else None,
        "role": role.code if role else None,
        # What the workspace calls the role, for the roles a client has no label for.
        "role_name": role.name if role else None,
        "is_member": is_member,
        "is_owner": is_owner,
        # Billing is not served here yet; these hold its place in the payload.
        "plan": None,
        "credits": None,
        "extensions": [],
    }


def _get_workspace_status(workspace, profile) -> str:
    if workspace and not workspace.is_active:
        if profile and profile.suspended_at:
            return "suspended"
        return "inactive"
    if profile and profile.is_suspended:
        return "suspended"
    return "active"


# ── Embedded mode ─────────────────────────────────────────────────────────────

def _is_platform_admin_embedded(user) -> bool:
    """Embedded: user is admin of the management Workspace."""
    from bfg.platform.utils import get_platform_workspace

    platform_ws = get_platform_workspace()
    if not platform_ws:
        return False
    StaffMember = apps.get_model("common", "StaffMember")
    # Cross-workspace: use unscoped manager so the answer doesn't depend on
    # whichever tenant the request happens to be bound to.
    return StaffMember.all_objects.filter(
        user=user, workspace=platform_ws, is_active=True, role__code="admin"
    ).exists()


# ── Standalone mode ───────────────────────────────────────────────────────────

def _is_platform_admin_standalone(user) -> bool:
    """Standalone: superuser or staff flag."""
    return getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)

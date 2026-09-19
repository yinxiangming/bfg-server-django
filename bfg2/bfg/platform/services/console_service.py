# -*- coding: utf-8 -*-
"""
What the console shows about each workspace, and to whom.

The console is shared by the platform's administrators and the owners of workspaces.
A platform administrator reaches every workspace on the install, suspended and
inactive ones included, whoever its staff are. An owner reaches the workspaces they
own, and only reads those that are suspended or inactive. An account that is neither
cannot use the console. ``ConsoleViewer`` works out which of these a caller is,
``console_workspaces`` is what they reach as a queryset, and ``workspace_entries``
turns workspaces from it into rows with a fixed number of queries, however many
workspaces there are.

Platform endpoints bind no workspace to the request, so tenant-scoped models are
read through ``all_objects`` here.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple

from django.apps import apps
from django.db.models import Count, Q

from bfg.common.extensions import registry
from bfg.common.extensions.endpoints import user_summary
from bfg.platform.services import workspace_service
from bfg.platform.services.ownership import owned_workspace_ids, workspace_owners
from bfg.platform.utils import is_platform_workspace

WORKSPACE_SUSPENDED = "workspace_suspended"
WORKSPACE_INACTIVE = "workspace_inactive"


@dataclass(frozen=True)
class ConsoleViewer:
    """Who is using the console: whether they administer the platform, and what they own.

    ``owned_ids`` is filled in for platform administrators too, since every row says
    whether its workspace is the viewer's own.
    """

    is_platform_admin: bool
    owned_ids: FrozenSet[int]

    @classmethod
    def of(cls, user) -> "ConsoleViewer":
        if not getattr(user, "is_authenticated", False):
            return cls(is_platform_admin=False, owned_ids=frozenset())
        return cls(
            # Global console visibility is a deployment control-plane privilege.
            # Non-superuser owners still see the workspaces they own below.
            is_platform_admin=workspace_service.is_platform_superuser(user),
            owned_ids=frozenset(owned_workspace_ids(user)),
        )

    @property
    def may_use_console(self) -> bool:
        return self.is_platform_admin or bool(self.owned_ids)

    def refusal_to_change(self, workspace) -> Optional[Tuple[str, str]]:
        """``(code, detail)`` when this viewer may look at *workspace* but not change its extensions.

        An owner only reads a workspace that is suspended, its profile carrying
        ``suspended_at``, or inactive. One that is both, as ``suspend_workspace``
        leaves it, is reported as suspended. A platform administrator is held back
        by neither, so for them this is always ``None``.
        """
        if self.is_platform_admin:
            return None
        if _suspended_at(workspace) is not None:
            return WORKSPACE_SUSPENDED, "This workspace is suspended, so its extensions cannot be changed."
        if not workspace.is_active:
            return WORKSPACE_INACTIVE, "This workspace is inactive, so its extensions cannot be changed."
        return None


def console_workspaces(viewer: ConsoleViewer, search: str = ""):
    """The workspaces *viewer* reaches, newest first.

    Every workspace for a platform administrator, and the ones they own for anyone
    else. *search* keeps those whose name or slug contains it, in any case.
    """
    Workspace = apps.get_model("common", "Workspace")
    workspaces = Workspace.objects.select_related("platform_profile").order_by("-created_at", "-id")
    if not viewer.is_platform_admin:
        workspaces = workspaces.filter(pk__in=viewer.owned_ids)
    search = (search or "").strip()
    if search:
        workspaces = workspaces.filter(Q(name__icontains=search) | Q(slug__icontains=search))
    return workspaces


def workspace_entries(workspaces, viewer: ConsoleViewer) -> list:
    """The console's row for each of *workspaces*, in their order.

    ``domains`` lists hostnames, the primary one first; ``owner`` is the account
    that owns the workspace, if any, and ``owned_by_viewer`` whether that account
    is *viewer*; ``staff_count`` counts active staff; and ``active_extensions``
    holds the keys of the deployed extensions the workspace has switched on,
    whether or not each is available to it right now.
    """
    workspaces = list(workspaces)
    ids = [workspace.pk for workspace in workspaces]
    owners = workspace_owners(ids)
    staff_counts = _active_staff_counts(ids)
    hostnames = _hostnames(ids)
    extension_keys = _active_extension_keys(ids)
    return [
        {
            "id": workspace.pk,
            "name": workspace.name,
            "slug": workspace.slug,
            "is_active": workspace.is_active,
            "is_platform": is_platform_workspace(workspace),
            "suspended_at": _suspended_at(workspace),
            **(
                {"scheduled_deletion_at": _scheduled_deletion_at(workspace)}
                if _scheduled_deletion_at(workspace) is not None else {}
            ),
            "created_at": workspace.created_at,
            "domains": hostnames.get(workspace.pk, []),
            "owner": user_summary(owners.get(workspace.pk)),
            "owned_by_viewer": workspace.pk in viewer.owned_ids,
            "staff_count": staff_counts.get(workspace.pk, 0),
            "active_extensions": extension_keys.get(workspace.pk, []),
        }
        for workspace in workspaces
    ]


def _suspended_at(workspace):
    profile = getattr(workspace, "platform_profile", None)
    return profile.suspended_at if profile else None


def _scheduled_deletion_at(workspace):
    profile = getattr(workspace, "platform_profile", None)
    return profile.scheduled_deletion_at if profile else None


def _active_staff_counts(ids) -> dict:
    StaffMember = apps.get_model("common", "StaffMember")
    rows = (
        StaffMember.all_objects.filter(workspace_id__in=ids, is_active=True)
        .values("workspace_id")
        .annotate(count=Count("id"))
        .order_by()
    )
    return {row["workspace_id"]: row["count"] for row in rows}


def _hostnames(ids) -> dict:
    WorkspaceDomain = apps.get_model("common", "WorkspaceDomain")
    hostnames = defaultdict(list)
    rows = (
        WorkspaceDomain.objects.filter(workspace_id__in=ids)
        .order_by("workspace_id", "-is_primary", "kind", "hostname")
        .values_list("workspace_id", "hostname")
    )
    for workspace_id, hostname in rows:
        hostnames[workspace_id].append(hostname)
    return hostnames


def _active_extension_keys(ids) -> dict:
    WorkspaceExtension = apps.get_model("common", "WorkspaceExtension")
    deployed = [manifest.key for manifest in registry.all_manifests() if manifest.is_activatable]
    keys = defaultdict(list)
    rows = (
        WorkspaceExtension.all_objects.filter(
            workspace_id__in=ids,
            status=WorkspaceExtension.STATUS_ACTIVE,
            key__in=deployed,
        )
        .order_by("workspace_id", "key")
        .values_list("workspace_id", "key")
    )
    for workspace_id, key in rows:
        keys[workspace_id].append(key)
    return keys

# -*- coding: utf-8 -*-
"""
Workspace ownership.

A workspace's owner is the user holding an active ``PlatformMembership`` with
role ``owner`` on the workspace's ``WorkspacePlatformProfile``. It is recorded
apart from ``StaffMember``, which only grants permissions inside the workspace:
an owner need not be staff there, and an admin is not thereby the owner.

``PlatformMembership`` has no constraint limiting a profile to one owner, so
``assign_workspace_owner`` is what keeps each workspace to one active owner.
"""
from django.apps import apps
from django.db import transaction

from bfg.core.exceptions import BFGException

OWNER_ROLE = "owner"


class WorkspaceAlreadyOwned(BFGException):
    """Another user already owns the workspace"""
    default_message = "Workspace already has an owner"
    default_code = "workspace_already_owned"


def owned_workspace_ids(user) -> list:
    """Ids of the workspaces *user* owns, in ascending order.

    Suspended and inactive workspaces are included: ownership does not lapse
    while a workspace is closed.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    PlatformMembership = apps.get_model("platform", "PlatformMembership")
    return list(
        PlatformMembership.objects.filter(
            user=user,
            role=OWNER_ROLE,
            is_active=True,
            # Standalone profiles can stand for a remote workspace with no local row.
            profile__workspace__isnull=False,
        )
        .order_by("profile__workspace_id")
        .values_list("profile__workspace_id", flat=True)
    )


def is_workspace_owner(user, workspace) -> bool:
    """Whether *user* owns *workspace*."""
    if workspace is None or not getattr(user, "is_authenticated", False):
        return False
    PlatformMembership = apps.get_model("platform", "PlatformMembership")
    return PlatformMembership.objects.filter(
        user=user,
        profile__workspace=workspace,
        role=OWNER_ROLE,
        is_active=True,
    ).exists()


def assign_workspace_owner(workspace, user):
    """Make *user* the owner of *workspace* and return the membership.

    Creates the workspace's platform profile when it has none. A membership
    *user* already holds becomes an active owner one; when it already is one,
    nothing is written.

    Raises ``WorkspaceAlreadyOwned`` when another user owns the workspace:
    handing a workspace to someone else is for the caller to decide, not a side
    effect of assigning an owner.
    """
    WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
    PlatformMembership = apps.get_model("platform", "PlatformMembership")

    with transaction.atomic():
        profile, _ = WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
        # Serialise assignments to one workspace; without the lock two callers
        # could both find it unowned and each add an owner.
        profile = WorkspacePlatformProfile.objects.select_for_update().get(pk=profile.pk)

        other_owner = (
            PlatformMembership.objects.filter(profile=profile, role=OWNER_ROLE, is_active=True)
            .exclude(user=user)
            .first()
        )
        if other_owner:
            raise WorkspaceAlreadyOwned(
                f"Workspace {profile.workspace_id} is already owned by user {other_owner.user_id}"
            )

        membership, created = PlatformMembership.objects.get_or_create(
            user=user,
            profile=profile,
            defaults={"role": OWNER_ROLE, "is_active": True},
        )
        if not created and (membership.role != OWNER_ROLE or not membership.is_active):
            membership.role = OWNER_ROLE
            membership.is_active = True
            membership.save(update_fields=["role", "is_active", "updated_at"])
    return membership

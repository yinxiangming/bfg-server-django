"""Workspace ownership: an active owner PlatformMembership, recorded apart from staff roles."""
import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from bfg.common.models import StaffMember, Workspace
from bfg.common.services.workspace_service import WorkspaceService
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile
from bfg.platform.services.ownership import (
    WorkspaceAlreadyOwned,
    assign_workspace_owner,
    is_workspace_owner,
    owned_workspace_ids,
)

User = get_user_model()


def _user(username):
    return User.objects.create_user(username=username, password="secret")


def _workspace(slug, **fields):
    return Workspace.objects.create(name=slug.title(), slug=slug, **fields)


def _writes(queries):
    """The captured statements that change data."""
    return [q["sql"] for q in queries if q["sql"].split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}]


def test_creating_a_workspace_records_its_owner(db):
    owner = _user("founder")

    workspace = WorkspaceService(workspace=None, user=owner).create_workspace(
        name="Acme", slug="acme", owner_user=owner,
    )

    membership = PlatformMembership.objects.get(profile__workspace=workspace)
    assert (membership.user, membership.role, membership.is_active) == (owner, "owner", True)
    assert is_workspace_owner(owner, workspace)
    # Ownership grants nothing inside the workspace; the owner still gets the admin role.
    assert StaffMember.all_objects.get(workspace=workspace, user=owner).role.code == "admin"


def test_creating_a_workspace_without_an_owner_records_none(db):
    workspace = WorkspaceService(workspace=None, user=None).create_workspace(name="Ownerless", slug="ownerless")

    assert not PlatformMembership.objects.filter(profile__workspace=workspace).exists()


def test_creating_a_workspace_without_bfg_platform_records_no_owner(db, monkeypatch):
    owner = _user("plain-owner")
    get_model = apps.get_model

    def get_model_without_platform(app_label, model_name=None, require_ready=True):
        if app_label.split(".")[0] == "platform":
            raise LookupError(f"No installed app with label '{app_label}'.")
        return get_model(app_label, model_name, require_ready=require_ready)

    monkeypatch.setattr(apps, "get_model", get_model_without_platform)

    workspace = WorkspaceService(workspace=None, user=owner).create_workspace(
        name="Plain", slug="plain", owner_user=owner,
    )

    assert StaffMember.all_objects.filter(workspace=workspace, user=owner, role__code="admin").exists()
    assert not PlatformMembership.objects.exists()


def test_assigning_an_owner_creates_the_missing_platform_profile(db):
    workspace = _workspace("legacy")
    owner = _user("legacy-owner")

    membership = assign_workspace_owner(workspace, owner)

    profile = WorkspacePlatformProfile.objects.get(workspace=workspace)
    assert (membership.profile, membership.user, membership.role, membership.is_active) == (
        profile, owner, "owner", True,
    )


def test_assigning_the_same_owner_again_writes_nothing(db):
    workspace = _workspace("again")
    owner = _user("again-owner")
    first = assign_workspace_owner(workspace, owner)

    with CaptureQueriesContext(connection) as queries:
        again = assign_workspace_owner(workspace, owner)

    assert again.pk == first.pk
    assert _writes(queries.captured_queries) == []
    assert PlatformMembership.objects.count() == 1


@pytest.mark.parametrize("role, is_active", [("staff", True), ("staff", False), ("owner", False)])
def test_assigning_an_owner_turns_their_existing_membership_into_an_active_owner(db, role, is_active):
    workspace = _workspace("existing")
    user = _user("existing-member")
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace)
    existing = PlatformMembership.objects.create(user=user, profile=profile, role=role, is_active=is_active)

    membership = assign_workspace_owner(workspace, user)

    assert membership.pk == existing.pk
    existing.refresh_from_db()
    assert (existing.role, existing.is_active) == ("owner", True)


def test_a_workspace_cannot_get_a_second_owner(db):
    workspace = _workspace("taken")
    assign_workspace_owner(workspace, _user("first-owner"))

    with pytest.raises(WorkspaceAlreadyOwned):
        assign_workspace_owner(workspace, _user("second-owner"))

    assert list(PlatformMembership.objects.values_list("user__username", "role")) == [("first-owner", "owner")]


def test_only_active_owner_memberships_count_as_ownership(db):
    user = _user("member")
    owned = _workspace("owned")
    closed = _workspace("closed", is_active=False)
    staff_only = _workspace("staff-only")
    former = _workspace("former")
    someone_elses = _workspace("someone-elses")

    assign_workspace_owner(owned, user)
    assign_workspace_owner(closed, user)
    WorkspacePlatformProfile.objects.filter(workspace=closed).update(suspended_at=timezone.now())
    PlatformMembership.objects.create(
        user=user, profile=WorkspacePlatformProfile.objects.create(workspace=staff_only), role="staff",
    )
    PlatformMembership.objects.create(
        user=user, profile=WorkspacePlatformProfile.objects.create(workspace=former), role="owner", is_active=False,
    )
    assign_workspace_owner(someone_elses, _user("someone-else"))

    # Closing or suspending a workspace does not end its ownership.
    assert owned_workspace_ids(user) == [owned.id, closed.id]
    assert is_workspace_owner(user, owned)
    assert is_workspace_owner(user, closed)
    for workspace in (staff_only, former, someone_elses):
        assert not is_workspace_owner(user, workspace)


def test_anonymous_users_own_nothing(db):
    workspace = _workspace("public")
    assign_workspace_owner(workspace, _user("real-owner"))

    assert owned_workspace_ids(AnonymousUser()) == []
    assert not is_workspace_owner(AnonymousUser(), workspace)

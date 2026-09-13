"""``backfill_workspace_owners``: previews by default, writes with --apply."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from bfg.common.models import StaffMember, StaffRole, Workspace
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile
from bfg.platform.services.ownership import assign_workspace_owner, owned_workspace_ids

User = get_user_model()


def backfill(*args):
    out = StringIO()
    call_command("backfill_workspace_owners", *args, stdout=out)
    return out.getvalue()


def _workspace(slug, with_profile=True):
    workspace = Workspace.objects.create(name=slug.title(), slug=slug, is_active=True)
    if with_profile:
        WorkspacePlatformProfile.objects.create(workspace=workspace)
    return workspace


def _staff(workspace, username, role_code="admin", days_ago=0, is_active=True):
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code=role_code, defaults={"name": role_code.title()},
    )
    user = User.objects.create_user(username=username, password="secret", email=f"{username}@example.test")
    StaffMember.all_objects.create(
        workspace=workspace, user=user, role=role, is_active=is_active,
        created_at=timezone.now() - timedelta(days=days_ago),
    )
    return user


def _owners(workspace):
    return list(
        PlatformMembership.objects.filter(profile__workspace=workspace, role="owner", is_active=True)
        .values_list("user__username", flat=True)
    )


def _writes(queries):
    """The captured statements that change data."""
    return [q["sql"] for q in queries if q["sql"].split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}]


def test_preview_lists_the_owners_and_writes_nothing(db):
    shop = _workspace("shop", with_profile=False)
    alice = _staff(shop, "alice")
    empty = _workspace("empty")

    with CaptureQueriesContext(connection) as queries:
        report = backfill()

    assert _writes(queries.captured_queries) == []
    assert not PlatformMembership.objects.exists()
    assert not WorkspacePlatformProfile.objects.filter(workspace=shop).exists()
    assert f"~ shop (id={shop.id}) → alice <alice@example.test> (user id={alice.id})" in report
    assert f"! empty (id={empty.id}) has no active admin — skipped" in report
    assert "Would assign 1 owner(s); skipped 1 workspace(s)" in report
    assert "nothing was written" in report


def test_apply_writes_each_owner_once(db):
    shop = _workspace("shop", with_profile=False)
    alice = _staff(shop, "alice")

    first = backfill("--apply")
    with CaptureQueriesContext(connection) as queries:
        second = backfill("--apply")

    assert owned_workspace_ids(alice) == [shop.id]
    assert PlatformMembership.objects.count() == 1
    assert _writes(queries.captured_queries) == []
    assert f"+ shop (id={shop.id}) → alice" in first
    assert "Assigned 1 owner(s)" in first
    assert "Assigned 0 owner(s)" in second
    assert "1 already have an owner" in second


def test_the_earliest_active_admin_becomes_the_owner(db):
    shop = _workspace("shop")
    _staff(shop, "clerk", role_code="staff", days_ago=40)
    _staff(shop, "former", days_ago=30, is_active=False)
    # Inserted before 'earliest', so ordering by id instead of by date would pick it.
    _staff(shop, "later", days_ago=10)
    _staff(shop, "earliest", days_ago=20)

    report = backfill("--apply")

    assert _owners(shop) == ["earliest"]
    assert "earliest of 2 active admins" in report


def test_a_workspace_without_an_active_admin_is_skipped_and_reported(db):
    shop = _workspace("no-admin", with_profile=False)
    _staff(shop, "clerk", role_code="staff")
    _staff(shop, "former", is_active=False)

    report = backfill("--apply")

    assert not PlatformMembership.objects.exists()
    # Nothing is written for a skipped workspace, not even its platform profile.
    assert not WorkspacePlatformProfile.objects.filter(workspace=shop).exists()
    assert f"! no-admin (id={shop.id}) has no active admin — skipped" in report
    assert "skipped 1 workspace(s) with no active admin" in report


def test_a_workspace_that_has_an_owner_is_left_alone(db):
    shop = _workspace("owned")
    _staff(shop, "first-admin", days_ago=30)
    owner = _staff(shop, "the-owner", days_ago=5)
    assign_workspace_owner(shop, owner)

    report = backfill("--apply")

    assert _owners(shop) == ["the-owner"]
    assert "first-admin" not in report
    assert "1 already have an owner" in report

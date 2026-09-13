"""``backfill_workspace_owners``: previews by default, writes with --apply, takes named owners with --owner."""
import re
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from bfg.common.models import StaffMember, StaffRole, Workspace
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile
from bfg.platform.services.ownership import assign_workspace_owner, owned_workspace_ids

User = get_user_model()

PREVIEW_AND_APPLY = [pytest.param((), id="preview"), pytest.param(("--apply",), id="apply")]


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
    # No password: the command never reads one, and hashing it made each test's setup slow.
    user = User.objects.create_user(username=username, email=f"{username}@example.test")
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


def _added(user):
    """The date the command prints for *user*'s staff membership."""
    return f"{StaffMember.all_objects.get(user=user).created_at:%Y-%m-%d}"


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


# --owner WORKSPACE=USER


@pytest.fixture
def shops(db):
    """Two workspaces with no owner and no platform profile.

    An operator set up "shop", so its earliest active admin is the operator, not
    the merchant added after. "other" has two admins of its own.
    """
    shop = _workspace("shop", with_profile=False)
    other = _workspace("other", with_profile=False)
    return SimpleNamespace(
        shop=shop,
        operator=_staff(shop, "operator", days_ago=30),
        merchant=_staff(shop, "merchant", days_ago=10),
        clerk=_staff(shop, "clerk", role_code="staff", days_ago=40),
        former=_staff(shop, "former", days_ago=50, is_active=False),
        other=other,
        first=_staff(other, "first", days_ago=20),
        second=_staff(other, "second", days_ago=5),
    )


def test_a_named_admin_becomes_the_owner_and_other_workspaces_still_get_their_earliest_admin(shops):
    report = backfill("--apply", "--owner", "shop=merchant")

    assert _owners(shops.shop) == ["merchant"]
    assert _owners(shops.other) == ["first"]
    assert (
        f"  + shop (id={shops.shop.id}) → merchant <merchant@example.test> (user id={shops.merchant.id}), "
        f"added {_added(shops.merchant)}, named with --owner\n"
    ) in report
    assert (
        f"  + other (id={shops.other.id}) → first <first@example.test> (user id={shops.first.id}), "
        f"added {_added(shops.first)}, earliest of 2 active admins\n"
    ) in report
    assert "Assigned 2 owner(s); skipped 0 workspace(s) with no active admin; 0 already have an owner." in report


@pytest.mark.parametrize("user_ref", ["id", "username", "email", "email in another case"])
@pytest.mark.parametrize("workspace_ref", ["id", "slug"])
def test_the_workspace_is_named_by_id_or_slug_and_the_user_by_id_username_or_email(shops, workspace_ref, user_ref):
    workspace = {"id": shops.shop.id, "slug": "shop"}[workspace_ref]
    user = {
        "id": shops.merchant.id,
        "username": "merchant",
        "email": "merchant@example.test",
        "email in another case": "Merchant@Example.TEST",
    }[user_ref]

    backfill("--apply", "--owner", f"{workspace}={user}")

    assert _owners(shops.shop) == ["merchant"]


@pytest.mark.parametrize("mode", PREVIEW_AND_APPLY)
@pytest.mark.parametrize("values, problem", [
    pytest.param(["shop"], "--owner 'shop': expected WORKSPACE=USER", id="no-equals-sign"),
    pytest.param(["=merchant"], "--owner '=merchant': expected WORKSPACE=USER", id="no-workspace"),
    pytest.param(["shop="], "--owner 'shop=': expected WORKSPACE=USER", id="no-user"),
    pytest.param(
        ["nowhere=merchant"], "--owner 'nowhere=merchant': no workspace with id or slug 'nowhere'",
        id="unknown-workspace",
    ),
    pytest.param(
        ["shop=nobody"], "--owner 'shop=nobody': no user with id, username or email 'nobody'",
        id="unknown-user",
    ),
    pytest.param(
        ["shop=clerk"],
        "--owner 'shop=clerk': clerk <clerk@example.test> (user id={clerk}) is not an active admin of shop (id={shop})",
        id="staff-but-not-admin",
    ),
    pytest.param(
        ["shop=former"],
        "--owner 'shop=former': former <former@example.test> (user id={former}) "
        "is not an active admin of shop (id={shop})",
        id="inactive-admin",
    ),
    pytest.param(
        ["shop=first"],
        "--owner 'shop=first': first <first@example.test> (user id={first}) is not an active admin of shop (id={shop})",
        id="admin-of-another-workspace",
    ),
    pytest.param(
        ["shop=merchant", "{shop}=operator"],
        "--owner '{shop}=operator': shop (id={shop}) is already named by --owner 'shop=merchant'",
        id="workspace-named-twice",
    ),
])
def test_a_bad_owner_value_stops_the_command_before_anything_is_written(shops, mode, values, problem):
    ids = {"shop": shops.shop.id, "clerk": shops.clerk.id, "former": shops.former.id, "first": shops.first.id}
    args = list(mode)
    for value in values:
        args += ["--owner", value.format(**ids)]
    out = StringIO()

    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(CommandError, match=re.escape(problem.format(**ids))):
            call_command("backfill_workspace_owners", *args, stdout=out)

    assert _writes(queries.captured_queries) == []
    assert not PlatformMembership.objects.exists()
    assert not WorkspacePlatformProfile.objects.exists()
    assert out.getvalue() == ""


def test_every_bad_owner_value_is_reported_at_once(shops):
    with pytest.raises(CommandError) as raised:
        backfill("--apply", "--owner", "shop", "--owner", "other=first", "--owner", "shop=nobody")

    assert str(raised.value) == (
        "Nothing was written. Fix these --owner values:\n"
        "  --owner 'shop': expected WORKSPACE=USER\n"
        "  --owner 'shop=nobody': no user with id, username or email 'nobody'"
    )
    assert not PlatformMembership.objects.exists()


@pytest.mark.parametrize("mode", PREVIEW_AND_APPLY)
def test_a_workspace_reference_that_is_one_id_and_another_slug_is_refused(shops, mode):
    ref = str(shops.shop.id)
    digits = _workspace(ref, with_profile=False)
    _staff(digits, "digits-admin")

    with pytest.raises(CommandError, match=re.escape(
        f"--owner '{ref}=merchant': '{ref}' matches more than one workspace: "
        f"shop (id={shops.shop.id}), {ref} (id={digits.id})"
    )):
        backfill(*mode, "--owner", f"{ref}=merchant")

    assert not PlatformMembership.objects.exists()


@pytest.mark.parametrize("mode", PREVIEW_AND_APPLY)
def test_a_user_reference_that_matches_two_users_is_refused(shops, mode):
    namesake = User.objects.create_user(username="namesake", password="secret", email="merchant@example.test")

    with pytest.raises(CommandError, match=re.escape(
        "--owner 'shop=merchant@example.test': 'merchant@example.test' matches more than one user: "
        f"merchant <merchant@example.test> (user id={shops.merchant.id}), "
        f"namesake <merchant@example.test> (user id={namesake.id})"
    )):
        backfill(*mode, "--owner", "shop=merchant@example.test")

    assert not PlatformMembership.objects.exists()


@pytest.mark.parametrize("mode", PREVIEW_AND_APPLY)
def test_a_named_workspace_that_someone_else_owns_keeps_its_owner_with_a_warning(shops, mode):
    assign_workspace_owner(shops.shop, shops.operator)

    report = backfill(*mode, "--owner", "shop=merchant")

    assert _owners(shops.shop) == ["operator"]
    assert (
        f"  ! shop (id={shops.shop.id}) is already owned by operator <operator@example.test> "
        f"(user id={shops.operator.id}) — skipped --owner 'shop=merchant'; ownership is not transferred\n"
    ) in report
    # The rest of the run goes ahead.
    assert _owners(shops.other) == (["first"] if mode else [])
    assert "1 owner(s); skipped 0 workspace(s) with no active admin; 1 already have an owner." in report


def test_a_named_workspace_that_its_named_admin_already_owns_counts_as_owned(shops):
    assign_workspace_owner(shops.shop, shops.merchant)
    assign_workspace_owner(shops.other, shops.second)

    with CaptureQueriesContext(connection) as queries:
        report = backfill("--apply", "--owner", "shop=merchant")

    assert _writes(queries.captured_queries) == []
    assert _owners(shops.shop) == ["merchant"]
    assert "already owned by" not in report
    assert "Assigned 0 owner(s); skipped 0 workspace(s) with no active admin; 2 already have an owner." in report


def test_preview_marks_the_named_owner_and_writes_nothing(shops):
    with CaptureQueriesContext(connection) as queries:
        report = backfill("--owner", "shop=merchant")

    assert _writes(queries.captured_queries) == []
    assert not PlatformMembership.objects.exists()
    assert not WorkspacePlatformProfile.objects.exists()
    assert report == (
        f"  ~ shop (id={shops.shop.id}) → merchant <merchant@example.test> (user id={shops.merchant.id}), "
        f"added {_added(shops.merchant)}, named with --owner\n"
        f"  ~ other (id={shops.other.id}) → first <first@example.test> (user id={shops.first.id}), "
        f"added {_added(shops.first)}, earliest of 2 active admins\n"
        "\n"
        "Would assign 2 owner(s); skipped 0 workspace(s) with no active admin; 0 already have an owner.\n"
        "Preview only — nothing was written. Run again with --apply to write these owners.\n"
    )

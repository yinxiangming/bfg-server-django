"""Entitlements: what a workspace may use, and what the extension system asks about it."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from bfg.common.extensions.manifest import (
    PRICING_ADDON,
    PRICING_CORE,
    SCOPE_PLATFORM,
    ExtensionManifest,
)
from bfg.common.models import Workspace
from bfg.platform.models import WorkspaceEntitlement
from bfg.platform.services import entitlements
from bfg.platform.services import platform_variables as variables
from bfg.shop.models import SubscriptionPlan

ADDON = ExtensionManifest(key="reviews", name="Reviews")
CORE = ExtensionManifest(key="sign_in", name="Sign-in", scope=SCOPE_PLATFORM)


@pytest.fixture(autouse=True)
def clear_variable_cache():
    """``grace_days`` is read through a cache that would otherwise outlive the test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name="Entitled", slug="entitled-ws", is_active=True)


def _entitlement(workspace, **fields):
    fields.setdefault("key", "reviews")
    return WorkspaceEntitlement.all_objects.create(workspace=workspace, **fields)


def test_a_workspace_with_no_entitlement_may_not_use_the_addon(workspace):
    assert entitlements.is_entitled(workspace, "reviews") is False


def test_an_active_entitlement_with_no_period_end_does_not_expire(workspace):
    row = _entitlement(workspace, status=WorkspaceEntitlement.STATUS_ACTIVE)

    assert row.is_live() is True
    assert entitlements.is_entitled(workspace, "reviews") is True


def test_a_period_that_is_still_running_counts(workspace):
    _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() + timedelta(days=5),
    )

    assert entitlements.is_entitled(workspace, "reviews") is True


def test_a_period_that_ran_out_yesterday_is_still_within_its_grace(workspace):
    row = _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() - timedelta(days=1),
    )

    assert row.is_live() is True
    assert entitlements.is_entitled(workspace, "reviews") is True


def test_a_period_that_ran_out_longer_ago_than_the_grace_has_lapsed(workspace):
    # Still marked active: nothing has swept it, and nothing has to have.
    row = _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() - timedelta(days=20),
    )

    assert row.is_live() is False
    assert entitlements.is_entitled(workspace, "reviews") is False


def test_how_long_a_lapsed_period_keeps_working_is_the_deployment_s_to_set(workspace):
    _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() - timedelta(days=20),
    )
    assert entitlements.is_entitled(workspace, "reviews") is False

    variables.set_variable("grace_days", 30, user=None, reason="test")
    assert entitlements.is_entitled(workspace, "reviews") is True

    variables.set_variable("grace_days", 3, user=None, reason="test")
    assert entitlements.is_entitled(workspace, "reviews") is False


def test_a_row_can_be_asked_about_a_moment_other_than_now(workspace):
    row = _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() + timedelta(days=5),
    )

    assert row.is_live() is True
    # Five days of period and fourteen of grace are both behind it by then.
    assert row.is_live(at=timezone.now() + timedelta(days=30)) is False


def test_an_entitlement_in_its_grace_period_still_counts(workspace):
    _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_GRACE,
        grace_until=timezone.now() + timedelta(days=3),
    )

    assert entitlements.is_entitled(workspace, "reviews") is True


def test_a_grace_period_that_has_run_out_does_not(workspace):
    _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_GRACE,
        grace_until=timezone.now() - timedelta(minutes=1),
    )

    assert entitlements.is_entitled(workspace, "reviews") is False


def test_a_grace_period_with_no_deadline_has_not_run_out(workspace):
    row = _entitlement(workspace, status=WorkspaceEntitlement.STATUS_GRACE)

    assert row.is_live() is True
    assert entitlements.is_entitled(workspace, "reviews") is True


def test_a_grace_row_answers_on_its_deadline_rather_than_on_the_grace_variable(workspace):
    # ``grace_until`` was worked out when the row was moved to grace; changing the
    # deployment's grace period afterwards does not move a deadline already set.
    _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_GRACE,
        current_period_end=timezone.now() - timedelta(days=1),
        grace_until=timezone.now() - timedelta(hours=1),
    )
    variables.set_variable("grace_days", 60, user=None, reason="test")

    assert entitlements.is_entitled(workspace, "reviews") is False


def test_an_ended_entitlement_does_not(workspace):
    _entitlement(
        workspace, status=WorkspaceEntitlement.STATUS_ENDED, ended_reason="not renewed"
    )

    assert entitlements.is_entitled(workspace, "reviews") is False


def test_one_live_period_is_enough_however_many_have_ended(workspace):
    _entitlement(workspace, status=WorkspaceEntitlement.STATUS_ENDED)
    _entitlement(workspace, status=WorkspaceEntitlement.STATUS_ENDED)
    _entitlement(workspace, status=WorkspaceEntitlement.STATUS_ACTIVE)

    assert entitlements.is_entitled(workspace, "reviews") is True


def test_an_entitlement_belongs_to_one_workspace_and_one_key(workspace):
    other = Workspace.objects.create(name="Other", slug="other-entitled", is_active=True)
    _entitlement(workspace, status=WorkspaceEntitlement.STATUS_ACTIVE)

    assert entitlements.is_entitled(other, "reviews") is False
    assert entitlements.is_entitled(workspace, "maps") is False


def test_the_base_plan_is_entitled_under_its_own_empty_key(workspace):
    _entitlement(
        workspace,
        key=WorkspaceEntitlement.KEY_BASE_PLAN,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
    )

    assert entitlements.is_entitled(workspace) is True
    assert entitlements.is_entitled(workspace, "reviews") is False


def test_no_workspace_is_entitled_to_nothing(db):
    assert entitlements.is_entitled(None, "reviews") is False


# ── Granting ─────────────────────────────────────────────────────────


def test_a_grant_is_active_from_now_and_says_why_it_was_given(workspace):
    granted = entitlements.grant(workspace, "reviews", reason="apology for the outage")

    assert granted.source == WorkspaceEntitlement.SOURCE_GRANTED
    assert granted.status == WorkspaceEntitlement.STATUS_ACTIVE
    assert granted.reason == "apology for the outage"
    assert granted.current_period_end is None
    assert entitlements.is_entitled(workspace, "reviews") is True


def test_a_grant_of_so_many_months_ends_on_the_same_day_of_a_later_month(workspace):
    granted = entitlements.grant(workspace, "reviews", months=3)

    assert granted.current_period_end is not None
    expected = entitlements.add_months(granted.starts_at, 3)
    assert granted.current_period_end == expected


def test_a_grant_can_stand_for_a_plan(workspace):
    plan = SubscriptionPlan.objects.create(workspace=workspace, name="Growth", price=Decimal("49"))

    granted = entitlements.grant(workspace, months=12, plan=plan, reason="bundled")

    assert granted.plan == plan
    assert granted.key == WorkspaceEntitlement.KEY_BASE_PLAN


# ── The hook the extension system calls ──────────────────────────────


def test_an_extension_in_the_base_plan_needs_no_entitlement(workspace):
    assert CORE.pricing == PRICING_CORE
    assert entitlements.entitlement_check(workspace, CORE) is True


def test_an_addon_is_checked_against_the_entitlement_table(workspace):
    assert ADDON.pricing == PRICING_ADDON
    assert entitlements.entitlement_check(workspace, ADDON) is False

    entitlements.grant(workspace, ADDON.key)

    assert entitlements.entitlement_check(workspace, ADDON) is True

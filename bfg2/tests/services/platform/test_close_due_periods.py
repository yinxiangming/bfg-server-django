"""Closing entitlement periods: grace, ending, and what an ending pauses."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from bfg.common.models import Workspace, WorkspaceExtension
from bfg.platform.models import WorkspaceEntitlement
from bfg.platform.services import entitlements
from bfg.platform.services import platform_variables as variables

KEY = "reviews"


@pytest.fixture(autouse=True)
def clear_caches():
    """``grace_days`` and the availability answer are both cached."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name="Closing", slug="closing-ws", is_active=True)


def _entitlement(workspace, **fields):
    fields.setdefault("key", KEY)
    fields.setdefault("status", WorkspaceEntitlement.STATUS_ACTIVE)
    return WorkspaceEntitlement.all_objects.create(workspace=workspace, **fields)


def _extension(workspace, key=KEY, status=WorkspaceExtension.STATUS_ACTIVE):
    return WorkspaceExtension.all_objects.create(workspace=workspace, key=key, status=status)


# ── Active → grace ───────────────────────────────────────────────────


def test_a_period_that_has_ended_moves_into_grace_counted_from_the_period_end(workspace):
    ended_at = timezone.now() - timedelta(days=2)
    row = _entitlement(workspace, current_period_end=ended_at)

    settled = entitlements.close_due_periods()

    row.refresh_from_db()
    assert settled["moved_to_grace"] == 1
    assert row.status == WorkspaceEntitlement.STATUS_GRACE
    # Fourteen days of grace, from when the period ended rather than from the sweep,
    # so running late does not hand out grace the deployment did not owe.
    assert row.grace_until == ended_at + timedelta(days=14)


def test_a_period_still_running_is_left_alone(workspace):
    row = _entitlement(workspace, current_period_end=timezone.now() + timedelta(days=5))

    settled = entitlements.close_due_periods()

    row.refresh_from_db()
    assert settled == {"moved_to_grace": 0, "ended": 0, "extensions_paused": 0}
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE


def test_an_entitlement_with_no_period_end_never_falls_due(workspace):
    row = _entitlement(workspace, current_period_end=None)

    entitlements.close_due_periods()

    row.refresh_from_db()
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE


def test_how_long_the_grace_is_is_the_deployment_s_to_set(workspace):
    variables.set_variable("grace_days", 3, user=None, reason="test")
    ended_at = timezone.now() - timedelta(hours=1)
    row = _entitlement(workspace, current_period_end=ended_at)

    entitlements.close_due_periods()

    row.refresh_from_db()
    assert row.grace_until == ended_at + timedelta(days=3)


# ── Grace → ended ────────────────────────────────────────────────────


def test_a_grace_period_that_has_run_out_ends_and_says_why(workspace):
    row = _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_GRACE,
        current_period_end=timezone.now() - timedelta(days=20),
        grace_until=timezone.now() - timedelta(days=1),
    )

    settled = entitlements.close_due_periods()

    row.refresh_from_db()
    assert settled["ended"] == 1
    assert row.status == WorkspaceEntitlement.STATUS_ENDED
    assert row.ended_reason == entitlements.ENDED_REASON


def test_a_grace_period_still_running_is_left_alone(workspace):
    row = _entitlement(
        workspace,
        status=WorkspaceEntitlement.STATUS_GRACE,
        grace_until=timezone.now() + timedelta(days=1),
    )

    entitlements.close_due_periods()

    row.refresh_from_db()
    assert row.status == WorkspaceEntitlement.STATUS_GRACE


def test_a_grace_row_with_no_deadline_is_not_ended_by_the_sweep(workspace):
    # ``grant`` can leave one open-ended; only a deadline that has passed ends it.
    row = _entitlement(workspace, status=WorkspaceEntitlement.STATUS_GRACE, grace_until=None)

    entitlements.close_due_periods()

    row.refresh_from_db()
    assert row.status == WorkspaceEntitlement.STATUS_GRACE


def test_a_period_that_ran_out_long_ago_goes_all_the_way_in_one_sweep(workspace):
    row = _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))

    settled = entitlements.close_due_periods()

    row.refresh_from_db()
    assert settled["moved_to_grace"] == 1
    assert settled["ended"] == 1
    assert row.status == WorkspaceEntitlement.STATUS_ENDED


def test_the_sweep_can_be_asked_about_a_moment_other_than_now(workspace):
    row = _entitlement(workspace, current_period_end=timezone.now() + timedelta(days=5))

    entitlements.close_due_periods(at=timezone.now() + timedelta(days=30))

    row.refresh_from_db()
    assert row.status == WorkspaceEntitlement.STATUS_ENDED


# ── Idempotence ──────────────────────────────────────────────────────


def test_running_the_sweep_twice_settles_nothing_the_second_time(workspace):
    _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))
    _extension(workspace)

    first = entitlements.close_due_periods()
    second = entitlements.close_due_periods()

    assert first == {"moved_to_grace": 1, "ended": 1, "extensions_paused": 1}
    assert second == {"moved_to_grace": 0, "ended": 0, "extensions_paused": 0}


def test_an_entitlement_already_ended_is_not_touched_again(workspace):
    row = _entitlement(workspace, status=WorkspaceEntitlement.STATUS_ENDED, ended_reason="refunded")

    entitlements.close_due_periods()

    row.refresh_from_db()
    assert row.ended_reason == "refunded"


# ── What ending one pauses ───────────────────────────────────────────


def test_ending_an_entitlement_pauses_the_extension_it_paid_for(workspace):
    _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))
    record = _extension(workspace)

    settled = entitlements.close_due_periods()

    record.refresh_from_db()
    assert settled["extensions_paused"] == 1
    assert record.status == WorkspaceExtension.STATUS_PAUSED
    assert record.status_reason == entitlements.PAUSED_REASON
    # Nobody switched it off, so nobody is recorded as having done so.
    assert record.status_changed_by is None
    # Paused, not archived: the configuration is still there to come back to.
    assert record.config == {}


def test_pausing_drops_the_workspace_s_cached_list_of_what_is_available(
    workspace, django_capture_on_commit_callbacks
):
    from bfg.common.extensions.services import available_cache_key

    _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))
    _extension(workspace)
    cache.set(available_cache_key(workspace.id), [KEY], 300)

    with django_capture_on_commit_callbacks(execute=True):
        entitlements.close_due_periods()

    assert cache.get(available_cache_key(workspace.id)) is None


def test_the_base_plan_has_no_extension_to_pause(workspace):
    _entitlement(
        workspace,
        key=WorkspaceEntitlement.KEY_BASE_PLAN,
        current_period_end=timezone.now() - timedelta(days=40),
    )
    record = _extension(workspace)

    settled = entitlements.close_due_periods()

    record.refresh_from_db()
    assert settled["ended"] == 1
    assert settled["extensions_paused"] == 0
    assert record.status == WorkspaceExtension.STATUS_ACTIVE


def test_an_extension_the_workspace_is_still_entitled_to_keeps_running(workspace):
    # The old period ending is what a renewal looks like: a new row, not a moved one.
    _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))
    _entitlement(workspace, current_period_end=timezone.now() + timedelta(days=30))
    record = _extension(workspace)

    settled = entitlements.close_due_periods()

    record.refresh_from_db()
    assert settled["ended"] == 1
    assert settled["extensions_paused"] == 0
    assert record.status == WorkspaceExtension.STATUS_ACTIVE


def test_an_extension_the_workspace_had_already_switched_off_is_left_as_it_was(workspace):
    _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))
    record = _extension(workspace, status=WorkspaceExtension.STATUS_INACTIVE)

    settled = entitlements.close_due_periods()

    record.refresh_from_db()
    assert settled["extensions_paused"] == 0
    assert record.status == WorkspaceExtension.STATUS_INACTIVE


def test_one_workspace_s_lapse_does_not_pause_another_s_extension(db):
    lapsed = Workspace.objects.create(name="Lapsed", slug="lapsed-ws", is_active=True)
    paid_up = Workspace.objects.create(name="Paid", slug="paid-ws", is_active=True)
    _entitlement(lapsed, current_period_end=timezone.now() - timedelta(days=40))
    _entitlement(paid_up, key="maps", current_period_end=timezone.now() - timedelta(days=40))
    theirs = _extension(lapsed)
    # Same workspace as one that lapsed, but a different key; and the same key as
    # one that lapsed, but a different workspace. Neither pair actually lapsed.
    other_key = _extension(lapsed, key="maps")
    other_workspace = _extension(paid_up, key=KEY)
    WorkspaceEntitlement.all_objects.create(
        workspace=lapsed, key="maps", status=WorkspaceEntitlement.STATUS_ACTIVE
    )
    WorkspaceEntitlement.all_objects.create(
        workspace=paid_up, key=KEY, status=WorkspaceEntitlement.STATUS_ACTIVE
    )

    settled = entitlements.close_due_periods()

    for record in (theirs, other_key, other_workspace):
        record.refresh_from_db()
    assert settled["extensions_paused"] == 1
    assert theirs.status == WorkspaceExtension.STATUS_PAUSED
    assert other_key.status == WorkspaceExtension.STATUS_ACTIVE
    assert other_workspace.status == WorkspaceExtension.STATUS_ACTIVE


def test_the_sweep_costs_the_same_number_of_queries_however_many_workspaces(db):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def lapse(count, offset):
        for index in range(count):
            workspace = Workspace.objects.create(
                name=f"Sweep {offset + index}", slug=f"sweep-{offset + index}", is_active=True
            )
            _entitlement(workspace, current_period_end=timezone.now() - timedelta(days=40))
            _extension(workspace)

    lapse(1, 0)
    # Read once up front: the grace period is cached after the first look, and a
    # cache that fills during the first measurement would make it the larger one.
    variables.get_variable("grace_days")
    with CaptureQueriesContext(connection) as one_workspace:
        entitlements.close_due_periods()

    lapse(12, 100)
    with CaptureQueriesContext(connection) as many_workspaces:
        settled = entitlements.close_due_periods()

    assert settled["extensions_paused"] == 12
    assert len(many_workspaces) == len(one_workspace)

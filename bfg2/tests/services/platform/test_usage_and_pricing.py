"""Pricing a meter, counting what a workspace used, and refusing it once the month's cap is gone."""

from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from bfg.common.models import Workspace
from bfg.platform.models import MeterPrice, UsageRecord, WorkspacePlatformProfile
from bfg.platform.services import platform_variables as variables
from bfg.platform.services import pricing, usage

METER = "vendor.lookup"


def at(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=datetime_timezone.utc)


@pytest.fixture(autouse=True)
def clear_variable_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name="Metered", slug="metered-ws", is_active=True)


@pytest.fixture
def price(db):
    """$5.00 per 1,000 lookups, on the deployment's default margin."""
    return MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("5"), unit_size=1000, effective_from=at(2026, 1, 1)
    )


# ── Prices ───────────────────────────────────────────────────────────


def test_the_price_in_force_is_the_latest_one_that_had_started(db, price):
    dearer = MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("8"), unit_size=1000, effective_from=at(2026, 6, 1, 0, 0)
    )

    assert pricing.price_for(METER, at=at(2026, 5, 31)) == price
    # A price applies from the moment it is effective, not from the moment after.
    assert pricing.price_for(METER, at=at(2026, 6, 1, 0, 0)) == dearer
    assert pricing.price_for(METER, at=at(2026, 12, 1)) == dearer


def test_a_meter_with_no_price_yet_is_refused_rather_than_counted_as_free(db, price):
    with pytest.raises(pricing.MeterNotPriced):
        pricing.price_for("vendor.never_priced", at=at(2026, 5, 1))
    with pytest.raises(pricing.MeterNotPriced):
        pricing.price_for(METER, at=at(2025, 12, 31))


def test_points_spread_the_vendor_cost_over_the_unit_and_add_the_default_margin(db, price):
    # 5 / 1000 = 0.005 a lookup, plus 30%, times 200 lookups.
    assert pricing.points_for(METER, 200, at=at(2026, 2, 1)) == Decimal("1.30000000")


def test_a_price_can_carry_its_own_margin_instead_of_the_platform_one(db):
    MeterPrice.objects.create(
        meter="vendor.at_cost",
        vendor_cost=Decimal("2"),
        unit_size=1,
        margin=Decimal("0"),
        effective_from=at(2026, 1, 1),
    )

    assert pricing.points_for("vendor.at_cost", 3, at=at(2026, 2, 1)) == Decimal("6.00000000")


def test_changing_the_platform_margin_moves_every_price_that_has_none_of_its_own(db, price):
    variables.set_variable("usage_margin", Decimal("1"), user=None, reason="test")

    assert pricing.points_for(METER, 1000, at=at(2026, 2, 1)) == Decimal("10.00000000")


# ── Recording usage ──────────────────────────────────────────────────


def test_recording_usage_stores_the_day_the_quantity_and_the_price_it_used(db, workspace, price):
    record = usage.record_usage(workspace, METER, 100, at=at(2026, 3, 4))

    assert record.day == date(2026, 3, 4)
    assert record.quantity == Decimal("100")
    assert record.points == Decimal("0.65")
    assert record.price == price


def test_a_second_call_on_the_same_day_adds_to_the_same_row(db, workspace, price):
    usage.record_usage(workspace, METER, 100, at=at(2026, 3, 4, 9))
    record = usage.record_usage(workspace, METER, 50, at=at(2026, 3, 4, 17))

    assert UsageRecord.all_objects.count() == 1
    assert record.quantity == Decimal("150")
    assert record.points == Decimal("0.975")


def test_usage_is_kept_apart_by_day_and_by_meter(db, workspace, price):
    MeterPrice.objects.create(
        meter="vendor.other", vendor_cost=Decimal("1"), unit_size=1, effective_from=at(2026, 1, 1)
    )
    usage.record_usage(workspace, METER, 10, at=at(2026, 3, 4))
    usage.record_usage(workspace, METER, 10, at=at(2026, 3, 5))
    usage.record_usage(workspace, "vendor.other", 1, at=at(2026, 3, 5))

    assert UsageRecord.all_objects.count() == 3


def test_the_day_a_call_belongs_to_is_its_UTC_day(db, workspace, price):
    late = usage.record_usage(workspace, METER, 1, at=at(2026, 3, 4, 23, 59))
    early = usage.record_usage(workspace, METER, 1, at=at(2026, 3, 5, 0, 1))

    assert late.day == date(2026, 3, 4)
    assert early.day == date(2026, 3, 5)


def test_a_price_change_mid_day_splits_the_day_rather_than_repricing_it(db, workspace, price):
    dearer = MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("10"), unit_size=1000, effective_from=at(2026, 3, 4, 12)
    )

    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 4, 9))
    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 4, 15))

    rows = {row.price_id: row for row in UsageRecord.all_objects.filter(day=date(2026, 3, 4))}
    assert rows[price.id].points == Decimal("6.5")
    assert rows[dearer.id].points == Decimal("13")
    assert usage.points_used(workspace, month=date(2026, 3, 1)) == Decimal("19.5")


def test_recording_usage_of_an_unpriced_meter_raises(db, workspace):
    with pytest.raises(pricing.MeterNotPriced):
        usage.record_usage(workspace, "vendor.never_priced", 1)

    assert not UsageRecord.all_objects.exists()


def test_usage_recorded_in_error_can_be_backed_out(db, workspace, price):
    usage.record_usage(workspace, METER, 100, at=at(2026, 3, 4))
    record = usage.record_usage(workspace, METER, -100, at=at(2026, 3, 4))

    assert record.quantity == Decimal("0")
    assert record.points == Decimal("0")


# ── Reading it back ──────────────────────────────────────────────────


def test_a_month_totals_only_its_own_days(db, workspace, price):
    usage.record_usage(workspace, METER, 1000, at=at(2026, 2, 28))
    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 1))
    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 31))
    usage.record_usage(workspace, METER, 1000, at=at(2026, 4, 1))

    assert usage.points_used(workspace, month=date(2026, 3, 15)) == Decimal("13")
    assert usage.points_used(workspace, month=date(2026, 2, 1)) == Decimal("6.5")


def test_a_month_with_no_usage_is_zero_points_rather_than_nothing(db, workspace, price):
    assert usage.points_used(workspace, month=date(2026, 3, 1)) == Decimal("0")


def test_a_month_belongs_to_the_workspace_that_used_it(db, workspace, price):
    other = Workspace.objects.create(name="Other", slug="other-metered", is_active=True)
    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 4))
    usage.record_usage(other, METER, 2000, at=at(2026, 3, 4))

    assert usage.points_used(workspace, month=date(2026, 3, 1)) == Decimal("6.5")
    assert usage.points_used(other, month=date(2026, 3, 1)) == Decimal("13")


def test_usage_by_day_lists_each_day_and_meter_once(db, workspace, price):
    MeterPrice.objects.create(
        meter="vendor.other", vendor_cost=Decimal("1"), unit_size=1, effective_from=at(2026, 1, 1)
    )
    MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("10"), unit_size=1000, effective_from=at(2026, 3, 4, 12)
    )
    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 4, 9))
    usage.record_usage(workspace, METER, 1000, at=at(2026, 3, 4, 15))
    usage.record_usage(workspace, "vendor.other", 2, at=at(2026, 3, 5))

    assert usage.usage_by_day(workspace, month=date(2026, 3, 1)) == [
        {"day": date(2026, 3, 4), "meter": METER, "quantity": Decimal("2000"), "points": Decimal("19.5")},
        {"day": date(2026, 3, 5), "meter": "vendor.other", "quantity": Decimal("2"), "points": Decimal("2.6")},
    ]


def test_the_current_month_is_the_one_asked_about_by_default(db, workspace, price):
    now = timezone.now()
    usage.record_usage(workspace, METER, 1000, at=now)
    usage.record_usage(workspace, METER, 1000, at=now - timedelta(days=40))

    assert usage.points_used(workspace) == Decimal("6.5")


# ── Caps ─────────────────────────────────────────────────────────────


def test_a_workspace_with_no_cap_of_its_own_gets_the_deployment_default(db, workspace, price):
    usage.record_usage(workspace, METER, 1000, at=timezone.now())

    allowance = usage.allowance(workspace)

    assert allowance.cap == Decimal("20")
    assert allowance.used == Decimal("6.5")
    assert allowance.remaining == Decimal("13.5")
    assert usage.may_meter(workspace)


def test_a_workspace_can_be_given_a_cap_of_its_own(db, workspace, price):
    WorkspacePlatformProfile.objects.create(workspace=workspace, monthly_usage_cap_points=Decimal("5"))
    usage.record_usage(workspace, METER, 1000, at=timezone.now())

    assert usage.allowance(workspace).cap == Decimal("5")
    assert usage.may_meter(workspace) is False


def test_a_workspace_that_has_overshot_its_cap_has_nothing_remaining(db, workspace, price):
    WorkspacePlatformProfile.objects.create(workspace=workspace, monthly_usage_cap_points=Decimal("5"))
    usage.record_usage(workspace, METER, 10000, at=timezone.now())

    allowance = usage.allowance(workspace)

    assert allowance.used == Decimal("65")
    assert allowance.remaining == Decimal("0")


def test_last_month_s_usage_does_not_count_against_this_month_s_cap(db, workspace, price):
    WorkspacePlatformProfile.objects.create(workspace=workspace, monthly_usage_cap_points=Decimal("5"))
    usage.record_usage(workspace, METER, 10000, at=timezone.now() - timedelta(days=40))

    assert usage.may_meter(workspace)


def test_raising_the_default_cap_lifts_every_workspace_that_has_no_cap_of_its_own(db, workspace, price):
    usage.record_usage(workspace, METER, 10000, at=timezone.now())
    assert usage.may_meter(workspace) is False

    variables.set_variable("monthly_usage_cap_points", Decimal("100"), user=None, reason="test")

    assert usage.may_meter(workspace)


@pytest.mark.parametrize(
    "month, expected",
    [
        (date(2026, 3, 15), (date(2026, 3, 1), date(2026, 4, 1))),
        (date(2026, 12, 31), (date(2026, 12, 1), date(2027, 1, 1))),
        (at(2026, 1, 31, 23, 59), (date(2026, 1, 1), date(2026, 2, 1))),
    ],
)
def test_a_month_runs_from_its_first_day_to_the_next_month_s(month, expected):
    assert usage.month_bounds(month) == expected

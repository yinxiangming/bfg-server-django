"""``meter_prices``: read a meter's price history, and add a rate from a moment on."""

import re
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from bfg.common.middleware import get_current_workspace
from bfg.platform.models import MeterPrice

METER = "ai.gpt-4o-mini.input"
OTHER = "vendor.lookup"

pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command("meter_prices", *args, stdout=out, no_color=True)
    return out.getvalue()


def priced(meter=METER, cost="0.15", unit_size=1_000_000, margin=None, days_ago=1):
    return MeterPrice.objects.create(
        meter=meter,
        vendor_cost=Decimal(cost),
        unit_size=unit_size,
        margin=None if margin is None else Decimal(margin),
        effective_from=timezone.now() - timedelta(days=days_ago),
    )


def marked(output):
    """The lines the command marked as the price in force."""
    return [line.strip() for line in output.splitlines() if line.startswith("  * ")]


# ── list ─────────────────────────────────────────────────────────────


def test_listing_nothing_says_how_to_add_a_price():
    output = run("list")

    assert "No meter prices yet" in output
    assert "meter_prices set" in output


def test_listing_shows_the_cost_the_unit_the_margin_and_the_points_it_comes_to():
    priced(cost="0.15", unit_size=1_000_000, margin="0.30")

    output = run("list")

    assert METER in output
    assert "$0.150000 per 1,000,000" in output
    assert "margin 0.3000" in output
    # 0.15 / 1,000,000 with 30% on top.
    assert "0.00000020 pt per unit" in output


def test_a_price_with_no_margin_of_its_own_is_shown_at_the_deployments():
    priced(margin=None)

    output = run("list")

    assert "(deployment default)" in output


def test_every_price_of_a_meter_is_listed_newest_first_with_the_one_in_force_marked():
    priced(cost="0.10", days_ago=30)
    priced(cost="0.15", days_ago=1)
    MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("0.20"), unit_size=1_000_000,
        effective_from=timezone.now() + timedelta(days=30),
    )

    output = run("list")

    assert re.findall(r"\$[\d.]+", output) == ["$0.200000", "$0.150000", "$0.100000"]
    # The one in force is neither the newest row nor the oldest.
    assert len(marked(output)) == 1
    assert "$0.150000" in marked(output)[0]


def test_a_meter_whose_prices_all_start_later_is_called_out():
    MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("0.20"), unit_size=1_000_000,
        effective_from=timezone.now() + timedelta(days=30),
    )

    output = run("list")

    assert "nothing in force" in output
    assert marked(output) == []


def test_prices_are_grouped_by_meter_and_one_meter_can_be_asked_for():
    priced(meter=METER)
    priced(meter=OTHER, cost="17.00", unit_size=1000)

    everything = run("list")
    assert METER in everything and OTHER in everything

    one = run("list", "--meter", OTHER)
    assert OTHER in one and METER not in one


def test_asking_for_a_meter_that_has_no_prices_says_so():
    priced(meter=METER)

    output = run("list", "--meter", OTHER)

    assert f"No meter prices for {OTHER!r}" in output


def test_listing_refuses_the_options_that_belong_to_set():
    with pytest.raises(CommandError, match="does not take --cost"):
        run("list", "--cost", "0.15")

    with pytest.raises(CommandError, match="does not take a meter as an argument"):
        run("list", METER)


# ── set ──────────────────────────────────────────────────────────────


def test_setting_a_price_writes_it_and_reports_what_it_comes_to():
    output = run("set", METER, "--cost", "17.00", "--unit-size", "1000", "--margin", "0.30")

    price = MeterPrice.objects.get()
    assert price.meter == METER
    assert price.vendor_cost == Decimal("17.000000")
    assert price.unit_size == 1000
    assert price.margin == Decimal("0.3000")
    assert "$17.000000 per 1,000" in output
    assert "0.02210000 pt per unit" in output


def test_a_new_price_leaves_the_old_one_alone():
    old = priced(cost="0.10", days_ago=30)

    run("set", METER, "--cost", "0.15", "--unit-size", "1000000")

    old.refresh_from_db()
    assert old.vendor_cost == Decimal("0.100000")
    assert MeterPrice.objects.filter(meter=METER).count() == 2


def test_a_price_with_no_margin_follows_the_deployments():
    run("set", METER, "--cost", "0.15", "--unit-size", "1000000")

    assert MeterPrice.objects.get().margin is None


def test_a_price_takes_effect_now_unless_a_moment_is_given():
    before = timezone.now()

    run("set", METER, "--cost", "0.15", "--unit-size", "1000000")

    assert before <= MeterPrice.objects.get().effective_from <= timezone.now()


@pytest.mark.parametrize(
    "given, expected",
    [
        ("2026-10-01T00:00:00Z", datetime(2026, 10, 1, tzinfo=datetime_timezone.utc)),
        ("2026-10-01T13:30:00+13:00", datetime(2026, 10, 1, 0, 30, tzinfo=datetime_timezone.utc)),
        # No zone: read in the deployment's own, which is UTC under test.
        ("2026-10-01", datetime(2026, 10, 1, tzinfo=datetime_timezone.utc)),
    ],
)
def test_a_price_can_be_dated(given, expected):
    run("set", METER, "--cost", "0.15", "--unit-size", "1000000", "--from", given)

    assert MeterPrice.objects.get().effective_from == expected


def test_a_price_that_starts_later_is_reported_as_not_yet_in_force():
    priced(cost="0.10")
    later = (timezone.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    output = run("set", METER, "--cost", "0.15", "--unit-size", "1000000", "--from", later)

    assert "not in force" in output


def test_a_first_price_that_starts_later_says_the_meter_is_unpriced_until_then():
    later = (timezone.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    output = run("set", METER, "--cost", "0.15", "--unit-size", "1000000", "--from", later)

    assert "no price in force until" in output


# ── set: what it refuses ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "args, message",
    [
        (("set",), "needs the meter to price"),
        ((("set"), METER, "--unit-size", "1000"), "needs --cost"),
        ((("set"), METER, "--cost", "0.15"), "needs --unit-size"),
        ((("set"), METER, "--cost", "free", "--unit-size", "1000"), "--cost is a number"),
        ((("set"), METER, "--cost", "-1", "--unit-size", "1000"), "--cost cannot be negative"),
        ((("set"), METER, "--cost", "0.15", "--unit-size", "0"), "--unit-size is at least 1"),
        ((("set"), METER, "--cost", "0.15", "--unit-size", "lots"), "--unit-size is a whole number"),
        ((("set"), METER, "--cost", "0.15", "--unit-size", "1000", "--margin", "a third"), "--margin is a number"),
        ((("set"), METER, "--cost", "0.15", "--unit-size", "1000", "--from", "soon"), "--from is a date"),
        ((("set"), METER, "--cost", "0.15", "--unit-size", "1000", "--from", "2026-02-31"), "--from is a date"),
        ((("set"), "--meter", METER, "--cost", "0.15", "--unit-size", "1000"), "not --meter"),
        # Bigger than the columns hold: refused in words, not by the database.
        ((("set"), METER, "--cost", "9999999", "--unit-size", "1000"), "Nothing was written"),
        ((("set"), METER, "--cost", "0.15", "--unit-size", "1000", "--margin", "100"), "Nothing was written"),
        ((("set"), "x" * 200, "--cost", "0.15", "--unit-size", "1000"), "Nothing was written"),
    ],
)
def test_a_price_that_cannot_be_read_is_refused_with_a_reason(args, message):
    with pytest.raises(CommandError, match=message):
        run(*args)

    assert not MeterPrice.objects.exists()


def test_an_unknown_action_is_refused():
    with pytest.raises(CommandError, match="invalid choice"):
        run("delete", METER)


# ── platform data ────────────────────────────────────────────────────


def test_prices_are_read_and_written_with_no_workspace_bound():
    # Management commands have no request and so no tenant; a price belongs to
    # the deployment rather than to any one workspace.
    assert get_current_workspace() is None

    run("set", METER, "--cost", "0.15", "--unit-size", "1000000")

    assert get_current_workspace() is None
    assert METER in run("list")

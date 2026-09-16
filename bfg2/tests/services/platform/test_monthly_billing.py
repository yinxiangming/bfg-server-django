"""Issuing a month's bills, and what an unpaid one stops.

The management workspace issues; the billed workspace's owner is who it is made
out to. A point is a US dollar, converted into the workspace's own currency at
the day's rate, so every test here has a rate on file.
"""

from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from bfg.common.models import Customer, Settings, User, Workspace
from bfg.finance.models import Currency, ExchangeRate, Invoice, TaxRate
from bfg.platform.models import MeterPrice, WorkspaceEntitlement, WorkspacePlatformProfile
from bfg.platform.services import billing, ownership, usage
from bfg.platform.services import platform_variables as variables
from bfg.shop.models import SubscriptionPlan

METER = "vendor.lookup"
PERIOD = date(2026, 8, 1)
PLATFORM_SLUG = "management"


def at(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=datetime_timezone.utc)


@pytest.fixture(autouse=True)
def clear_caches():
    """Platform variables and the overdue answer are both cached."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def platform_mode(settings):
    settings.PLATFORM_WORKSPACE_SLUG = PLATFORM_SLUG


@pytest.fixture
def currencies(db):
    for code, places in (("USD", 2), ("NZD", 2), ("JPY", 0)):
        Currency.objects.update_or_create(
            code=code,
            defaults={"name": code, "symbol": code, "decimal_places": places, "is_active": True},
        )


@pytest.fixture
def rate(currencies):
    """1 US dollar is 1.60 New Zealand dollars, from yesterday."""
    return ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code="USD"),
        to_currency=Currency.objects.get(code="NZD"),
        effective_date=timezone.now().date() - timedelta(days=1),
        rate=Decimal("1.60"),
    )


@pytest.fixture
def platform(db):
    """The workspace that sells, priced in US dollars."""
    workspace = Workspace.objects.create(
        name="Management", slug=PLATFORM_SLUG, is_active=True
    )
    _settings(workspace, "USD", "NZ")
    return workspace


@pytest.fixture
def gst(platform):
    return TaxRate.objects.create(
        workspace=platform, name="GST", rate=Decimal("15.00"), country="NZ", is_active=True
    )


@pytest.fixture
def shop(db, platform):
    """A New Zealand workspace that buys, priced in New Zealand dollars."""
    workspace = Workspace.objects.create(name="Corner Shop", slug="corner-shop", is_active=True)
    _settings(workspace, "NZD", "NZ")
    return workspace


@pytest.fixture
def owner(shop):
    user = User.objects.create_user(username="owner", email="owner@example.com", password="x")
    ownership.assign_workspace_owner(shop, user)
    return user


@pytest.fixture
def price(db):
    """One point per call, so the points in a test are the calls in it."""
    return MeterPrice.objects.create(
        meter=METER,
        vendor_cost=Decimal("1"),
        unit_size=1,
        margin=Decimal("0"),
        effective_from=at(2026, 1, 1),
    )


@pytest.fixture
def plan(platform):
    return SubscriptionPlan.objects.create(workspace=platform, name="Growth", price=Decimal("49"))


def _renewal(workspace, plan, *, key="reviews", source=WorkspaceEntitlement.SOURCE_PURCHASED,
             ends=at(2026, 8, 20)):
    return WorkspaceEntitlement.all_objects.create(
        workspace=workspace,
        key=key,
        plan=plan,
        source=source,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=ends,
    )


def _settings(workspace, currency, country):
    """A workspace is created with settings already, so this changes them."""
    row, _ = Settings.objects.update_or_create(
        workspace=workspace, defaults={"default_currency": currency, "country": country}
    )
    return row


def _lines(bill):
    return [(line["description"], line["quantity"], line["unit_price"], line["subtotal"])
            for line in bill["lines"]]


# ── What a bill is made of ───────────────────────────────────────────


def test_a_bill_carries_the_renewal_the_usage_and_the_trial_credit(
    shop, owner, rate, price, plan, gst
):
    _renewal(shop, plan)
    usage.record_usage(shop, METER, 10, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["issued"] is True
    assert bill["currency"] == "NZD"
    assert _lines(bill) == [
        # US$49 a month, at 1.60.
        ("Growth — reviews renewal", Decimal("1"), Decimal("78.40"), Decimal("78.40")),
        # Ten points, a point being a US dollar.
        (f"{METER} — 10 metered units", Decimal("10.00"), Decimal("1.60"), Decimal("16.00")),
        ("Trial credit (1 points)", Decimal("1"), Decimal("-1.60"), Decimal("-1.60")),
    ]
    assert bill["subtotal"] == Decimal("92.80")
    assert bill["tax"] == Decimal("13.92")
    assert bill["total"] == Decimal("106.72")


def test_the_invoice_is_issued_by_the_management_workspace_to_the_owner(
    shop, owner, rate, price, platform
):
    usage.record_usage(shop, METER, 4, at=at(2026, 8, 5))

    billing.issue_monthly_bills(PERIOD)

    invoice = Invoice.all_objects.get(invoice_number=f"PLAT-{shop.id}-202608")
    assert invoice.workspace == platform
    assert invoice.customer.user == owner
    assert invoice.customer.workspace == platform
    assert invoice.currency.code == "NZD"
    assert invoice.items.count() == 2
    # The number is the only thing tying the invoice back to the shop it is about.
    assert str(shop.id) in invoice.invoice_number
    assert shop.name in invoice.notes


def test_the_invoice_falls_due_after_the_deployment_s_own_number_of_days(shop, owner, rate, price):
    variables.set_variable("invoice_due_days", 7, user=None, reason="test")
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    billing.issue_monthly_bills(PERIOD)

    invoice = Invoice.all_objects.get()
    assert invoice.issue_date == timezone.now().date()
    assert invoice.due_date == invoice.issue_date + timedelta(days=7)


def test_usage_is_one_line_per_meter_however_many_days_it_was_spread_over(shop, owner, rate, price):
    MeterPrice.objects.create(
        meter="vendor.other", vendor_cost=Decimal("2"), unit_size=1,
        margin=Decimal("0"), effective_from=at(2026, 1, 1),
    )
    usage.record_usage(shop, METER, 3, at=at(2026, 8, 5))
    usage.record_usage(shop, METER, 7, at=at(2026, 8, 19))
    usage.record_usage(shop, "vendor.other", 2, at=at(2026, 8, 19))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert [line["description"] for line in bill["lines"]] == [
        f"{METER} — 10 metered units",
        "vendor.other — 2 metered units",
        "Trial credit (1 points)",
    ]


def test_another_month_s_usage_is_not_on_this_month_s_bill(shop, owner, rate, price):
    usage.record_usage(shop, METER, 5, at=at(2026, 8, 31, 23))
    usage.record_usage(shop, METER, 100, at=at(2026, 9, 1, 1))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["lines"][0]["quantity"] == Decimal("5.00")


def test_an_entitlement_that_was_given_rather_than_bought_is_not_charged_for(
    shop, owner, rate, price, plan
):
    _renewal(shop, plan, source=WorkspaceEntitlement.SOURCE_GRANTED)
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert [line["description"] for line in bill["lines"]] == [
        f"{METER} — 1 metered units",
        "Trial credit (1 points)",
    ]


def test_a_workspace_with_nothing_chargeable_is_not_billed(shop, owner, rate, plan):
    _renewal(shop, plan, source=WorkspaceEntitlement.SOURCE_GRANTED)

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["issued"] is False
    assert bill["skipped"] == "nothing chargeable this period"
    assert not Invoice.all_objects.exists()


def test_an_entitlement_whose_period_ends_in_another_month_is_not_renewed_now(
    shop, owner, rate, price, plan
):
    _renewal(shop, plan, ends=at(2026, 9, 1, 0))
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert all("renewal" not in line["description"] for line in bill["lines"])


def test_the_month_billed_by_default_is_the_one_just_gone(shop, owner, rate, price):
    last_month = timezone.now().replace(day=1) - timedelta(days=1)
    usage.record_usage(shop, METER, 2, at=last_month)

    bill, = billing.issue_monthly_bills()

    assert bill["period"] == f"{last_month:%Y-%m}"
    assert bill["issued"] is True


# ── The trial credit ─────────────────────────────────────────────────


def test_the_trial_credit_is_taken_once_and_recorded_as_spent(shop, owner, rate, price):
    usage.record_usage(shop, METER, 5, at=at(2026, 8, 5))
    usage.record_usage(shop, METER, 5, at=at(2026, 9, 5))

    august, = billing.issue_monthly_bills(PERIOD)
    september, = billing.issue_monthly_bills(date(2026, 9, 1))

    assert any("Trial credit" in line["description"] for line in august["lines"])
    assert all("Trial credit" not in line["description"] for line in september["lines"])
    profile = WorkspacePlatformProfile.objects.get(workspace=shop)
    assert profile.trial_points_used_at is not None


def test_the_credit_never_makes_a_bill_negative(shop, owner, rate, price):
    variables.set_variable("trial_points", Decimal("100"), user=None, reason="test")
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["lines"][-1]["subtotal"] == Decimal("-1.60")
    assert bill["total"] == Decimal("0.00")


def test_a_deployment_that_offers_no_trial_credit_puts_no_line_on_the_bill(shop, owner, rate, price):
    variables.set_variable("trial_points", Decimal("0"), user=None, reason="test")
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert all("Trial credit" not in line["description"] for line in bill["lines"])


# ── Tax ──────────────────────────────────────────────────────────────


def test_a_new_zealand_workspace_is_taxed_over_the_whole_invoice(shop, owner, rate, price, gst):
    usage.record_usage(shop, METER, 10, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["subtotal"] == Decimal("14.40")
    assert bill["tax"] == Decimal("2.16")
    assert bill["total"] == Decimal("16.56")
    invoice = Invoice.all_objects.get()
    # The lines and the invoice's own tax column are the same number by construction.
    assert sum(item.tax for item in invoice.items.all()) == invoice.tax


def test_a_workspace_somewhere_else_is_billed_untaxed_for_now(db, platform, rate, price, gst):
    elsewhere = Workspace.objects.create(name="Sydney", slug="sydney-shop", is_active=True)
    _settings(elsewhere, "NZD", "AU")
    user = User.objects.create_user(username="au", email="au@example.com", password="x")
    ownership.assign_workspace_owner(elsewhere, user)
    usage.record_usage(elsewhere, METER, 10, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["tax"] == Decimal("0.00")
    assert bill["total"] == bill["subtotal"]


def test_a_deployment_that_has_recorded_no_tax_rate_bills_untaxed_and_says_so(
    shop, owner, rate, price, caplog
):
    usage.record_usage(shop, METER, 10, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["tax"] == Decimal("0.00")
    assert "tax rate" in caplog.text


# ── Skipping, and not billing twice ──────────────────────────────────


def test_a_workspace_with_no_owner_is_skipped_and_said_so(shop, rate, price):
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["issued"] is False
    assert bill["skipped"] == "no owner to bill"
    assert not Invoice.all_objects.exists()


def test_a_currency_with_no_rate_on_the_day_is_skipped_rather_than_billed_at_a_guess(
    db, platform, currencies, price
):
    elsewhere = Workspace.objects.create(name="Tokyo", slug="tokyo-shop", is_active=True)
    _settings(elsewhere, "JPY", "JP")
    user = User.objects.create_user(username="jp", email="jp@example.com", password="x")
    ownership.assign_workspace_owner(elsewhere, user)
    usage.record_usage(elsewhere, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["issued"] is False
    assert "no USD to JPY rate" in bill["skipped"]
    assert not Invoice.all_objects.exists()


def test_a_month_already_billed_is_not_billed_again(shop, owner, rate, price):
    usage.record_usage(shop, METER, 3, at=at(2026, 8, 5))
    first, = billing.issue_monthly_bills(PERIOD)

    second, = billing.issue_monthly_bills(PERIOD)

    assert first["issued"] is True
    assert second["issued"] is False
    assert second["skipped"] == "already billed for this period"
    assert Invoice.all_objects.count() == 1


def test_the_management_workspace_does_not_bill_itself(platform, rate, price):
    usage.record_usage(platform, METER, 5, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["skipped"] == "the platform does not bill itself"
    assert not Invoice.all_objects.exists()


def test_a_deployment_with_no_management_workspace_cannot_bill(shop, owner, rate, price, settings):
    settings.PLATFORM_WORKSPACE_SLUG = "not-a-workspace"
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    with pytest.raises(billing.PlatformWorkspaceMissing):
        billing.issue_monthly_bills(PERIOD)


def test_a_month_nobody_used_anything_in_produces_no_bills(shop, owner, rate, price):
    assert billing.issue_monthly_bills(date(2026, 7, 1)) == []


# ── Dry run ──────────────────────────────────────────────────────────


def test_a_dry_run_works_out_the_same_bill_and_writes_none_of_it(
    shop, owner, rate, price, plan, gst
):
    _renewal(shop, plan)
    usage.record_usage(shop, METER, 10, at=at(2026, 8, 5))

    planned, = billing.issue_monthly_bills(PERIOD, dry_run=True)
    issued, = billing.issue_monthly_bills(PERIOD)

    assert planned["issued"] is False
    assert _lines(planned) == _lines(issued)
    assert planned["total"] == issued["total"]


def test_a_dry_run_leaves_the_trial_credit_unspent_and_creates_no_customer(shop, owner, rate, price):
    usage.record_usage(shop, METER, 5, at=at(2026, 8, 5))

    billing.issue_monthly_bills(PERIOD, dry_run=True)

    assert not Invoice.all_objects.exists()
    assert not Customer.all_objects.exists()
    assert WorkspacePlatformProfile.objects.get(workspace=shop).trial_points_used_at is None


# ── What an unpaid bill stops ────────────────────────────────────────


def _bill(shop, *, due, status="sent", total=Decimal("20.00"), period=PERIOD):
    return Invoice.all_objects.create(
        workspace=Workspace.objects.get(slug=PLATFORM_SLUG),
        customer=Customer.all_objects.create(
            workspace=Workspace.objects.get(slug=PLATFORM_SLUG),
            user=User.objects.create_user(username=f"u{due}", password="x"),
        ),
        invoice_number=billing.invoice_number_for(shop.id, period),
        status=status,
        subtotal=total,
        tax=Decimal("0"),
        total=total,
        currency=Currency.objects.get(code="NZD"),
        issue_date=due - timedelta(days=14),
        due_date=due,
    )


def test_a_workspace_past_due_may_not_make_another_metered_call(shop, owner, rate, price):
    assert usage.may_meter(shop) is True
    _bill(shop, due=timezone.now().date() - timedelta(days=1))
    cache.clear()

    assert usage.may_meter(shop) is False


def test_a_bill_not_yet_due_stops_nothing(shop, owner, rate, price):
    _bill(shop, due=timezone.now().date() + timedelta(days=1))
    cache.clear()

    assert usage.may_meter(shop) is True


def test_a_bill_that_has_been_paid_stops_nothing(shop, owner, rate, price):
    _bill(shop, due=timezone.now().date() - timedelta(days=30), status="paid")
    cache.clear()

    assert usage.may_meter(shop) is True


def test_a_bill_that_came_to_nothing_is_not_a_debt(shop, owner, rate, price):
    _bill(shop, due=timezone.now().date() - timedelta(days=30), total=Decimal("0.00"))
    cache.clear()

    assert billing.has_overdue_invoice(shop) is False


def test_one_workspace_s_unpaid_bill_does_not_stop_another(shop, owner, rate, price, platform):
    other = Workspace.objects.create(name="Other", slug="other-shop", is_active=True)
    _bill(shop, due=timezone.now().date() - timedelta(days=1))
    cache.clear()

    assert billing.has_overdue_invoice(shop) is True
    assert billing.has_overdue_invoice(other) is False


def test_the_overdue_answer_is_asked_of_the_database_once_and_then_reused(shop, owner, rate):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _bill(shop, due=timezone.now().date() - timedelta(days=1))
    cache.clear()

    with CaptureQueriesContext(connection) as first:
        assert billing.has_overdue_invoice(shop) is True
    with CaptureQueriesContext(connection) as again:
        assert billing.has_overdue_invoice(shop) is True

    assert len(first) == 1
    assert len(again) == 0


# ── Reviewed hazards ─────────────────────────────────────────────────


def test_a_renewal_is_still_billed_after_the_sweep_has_ended_it(shop, owner, rate, price, plan):
    """The bill is for the month that ran, not for what is still live when it is issued.

    ``close_entitlement_periods`` runs daily and ends anything past its grace, so
    reading only live rows would have dropped every period ending in the first
    fortnight of a month — billed or not depending on which cron ran first.
    """
    from bfg.platform.services import entitlements

    _renewal(shop, plan)
    entitlements.close_due_periods()
    assert (
        WorkspaceEntitlement.all_objects.get().status == WorkspaceEntitlement.STATUS_ENDED
    )

    bill, = billing.issue_monthly_bills(PERIOD)

    assert [line["description"] for line in bill["lines"]] == [
        "Growth — reviews renewal",
        "Trial credit (1 points)",
    ]
    assert bill["total"] == Decimal("76.80")


def test_every_line_is_converted_at_the_rate_the_bank_published(shop, owner, currencies, price, plan):
    # A rate with more decimals than the currency has. Rounding it first and then
    # multiplying would overcharge a large quantity by up to half a cent a point.
    ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code="USD"),
        to_currency=Currency.objects.get(code="NZD"),
        effective_date=timezone.now().date(),
        rate=Decimal("1.6789"),
    )
    _renewal(shop, plan)
    usage.record_usage(shop, METER, 1000, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    renewal, metered, credit = bill["lines"]
    # 49 × 1.6789, and 1000 × 1.6789 — the same rate for both, not 1.68 for one.
    assert renewal["subtotal"] == Decimal("82.27")
    assert metered["subtotal"] == Decimal("1678.90")
    assert metered["unit_price"] == Decimal("1.68")
    assert credit["subtotal"] == Decimal("-1.68")
    # And the rate itself is on the invoice, so every line can be checked.
    assert "1.678900 NZD" in Invoice.all_objects.get().notes


def test_an_invoice_adds_up(shop, owner, rate, price, plan, gst):
    _renewal(shop, plan)
    usage.record_usage(shop, METER, 7, at=at(2026, 8, 5))

    billing.issue_monthly_bills(PERIOD)

    invoice = Invoice.all_objects.get()
    items = list(invoice.items.all())
    assert sum(item.subtotal for item in items) == invoice.subtotal
    assert sum(item.tax for item in items) == invoice.tax
    assert invoice.subtotal + invoice.tax == invoice.total


def test_an_invoice_a_workspace_numbered_itself_does_not_stop_anyone(shop, owner, rate, price):
    # A workspace chooses its own invoice prefix, so it can number an invoice into
    # another workspace's platform range. Only the management workspace's invoices
    # are a platform debt.
    other = Workspace.objects.create(name="Copycat", slug="copycat", is_active=True)
    Invoice.all_objects.create(
        workspace=other,
        customer=Customer.all_objects.create(
            workspace=other, user=User.objects.create_user(username="copy", password="x")
        ),
        invoice_number=billing.invoice_number_for(shop.id, PERIOD),
        status="sent",
        subtotal=Decimal("999"),
        tax=Decimal("0"),
        total=Decimal("999"),
        currency=Currency.objects.get(code="NZD"),
        issue_date=timezone.now().date() - timedelta(days=60),
        due_date=timezone.now().date() - timedelta(days=30),
    )
    cache.clear()

    assert billing.has_overdue_invoice(shop) is False


def test_reading_a_run_costs_the_same_number_of_queries_however_many_workspaces(
    platform, owner, rate, price, plan
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def billable(count, offset):
        for index in range(count):
            workspace = Workspace.objects.create(
                name=f"Shop {offset + index}", slug=f"shop-{offset + index}", is_active=True
            )
            _settings(workspace, "NZD", "NZ")
            ownership.assign_workspace_owner(
                workspace,
                User.objects.create_user(username=f"owner-{offset + index}", password="x"),
            )
            _renewal(workspace, plan)
            _renewal(workspace, plan, key="maps")
            usage.record_usage(workspace, METER, 3, at=at(2026, 8, 5))

    billable(1, 0)
    # Read once up front: the platform variables are cached after the first look,
    # and a cache that fills during the first measurement would inflate it.
    variables.get_variable("invoice_due_days")
    variables.get_variable("trial_points")
    with CaptureQueriesContext(connection) as one_workspace:
        billing.issue_monthly_bills(PERIOD, dry_run=True)

    billable(10, 100)
    with CaptureQueriesContext(connection) as many_workspaces:
        bills = billing.issue_monthly_bills(PERIOD, dry_run=True)

    assert len(bills) == 11
    assert len(many_workspaces) == len(one_workspace)


def test_a_clash_that_is_not_a_second_invoice_is_not_reported_as_one(
    shop, owner, rate, price, monkeypatch
):
    # Writing an invoice also writes a customer. Reporting every constraint clash
    # as "already billed" would let a workspace go unbilled with nothing in the
    # output but a line saying all was well.
    from django.db import IntegrityError

    from bfg.finance.models import InvoiceItem

    def refuse(*args, **kwargs):
        raise IntegrityError("something else objected")

    monkeypatch.setattr(InvoiceItem.objects, "bulk_create", refuse)
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    with pytest.raises(IntegrityError):
        billing.issue_monthly_bills(PERIOD)


def test_a_plan_priced_in_a_currency_with_no_rate_skips_that_workspace(shop, owner, rate, price):
    # The workspace's own currency converts; the plan's does not. The invoice is
    # left for the next run rather than issued with the renewal quietly missing.
    elsewhere = Workspace.objects.create(name="Tokyo HQ", slug="tokyo-hq", is_active=True)
    _settings(elsewhere, "JPY", "JP")
    _renewal(
        shop,
        SubscriptionPlan.objects.create(workspace=elsewhere, name="Growth", price=Decimal("5000")),
    )
    usage.record_usage(shop, METER, 1, at=at(2026, 8, 5))

    bill, = billing.issue_monthly_bills(PERIOD)

    assert bill["issued"] is False
    assert "No JPY to NZD rate" in bill["skipped"]
    assert not Invoice.all_objects.exists()

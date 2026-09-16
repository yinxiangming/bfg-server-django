"""The three commands an operator runs: closing periods, reading rates, issuing bills.

Neither deployment has a scheduler, so these are the whole of how the billing
month actually happens. Each one is exercised for what it writes, and for what a
dry run does not.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from bfg.common.models import Settings, User, Workspace, WorkspaceExtension
from bfg.finance.models import Currency, ExchangeRate, Invoice
from bfg.platform.models import MeterPrice, WorkspaceEntitlement
from bfg.platform.services import exchange_rates, ownership, usage

METER = "vendor.lookup"
PLATFORM_SLUG = "management"


@pytest.fixture(autouse=True)
def clear_caches():
    cache.clear()
    yield
    cache.clear()


def run(command, *args):
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


# ── close_entitlement_periods ────────────────────────────────────────


@pytest.fixture
def lapsed(db):
    workspace = Workspace.objects.create(name="Lapsed", slug="lapsed-cmd", is_active=True)
    WorkspaceEntitlement.all_objects.create(
        workspace=workspace,
        key="reviews",
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=timezone.now() - timedelta(days=40),
    )
    WorkspaceExtension.all_objects.create(
        workspace=workspace, key="reviews", status=WorkspaceExtension.STATUS_ACTIVE
    )
    return workspace


def test_closing_periods_settles_them_and_says_what_it_settled(lapsed):
    output = run("close_entitlement_periods")

    assert "Settled." in output
    assert WorkspaceEntitlement.all_objects.get().status == WorkspaceEntitlement.STATUS_ENDED
    assert WorkspaceExtension.all_objects.get().status == WorkspaceExtension.STATUS_PAUSED


def test_a_dry_run_reports_the_same_sweep_and_writes_none_of_it(lapsed):
    output = run("close_entitlement_periods", "--dry-run")

    assert "Dry run" in output
    assert WorkspaceEntitlement.all_objects.get().status == WorkspaceEntitlement.STATUS_ACTIVE
    assert WorkspaceExtension.all_objects.get().status == WorkspaceExtension.STATUS_ACTIVE


def test_closing_periods_with_nothing_due_says_so(db):
    assert "Nothing had run out." in run("close_entitlement_periods")


# ── refresh_exchange_rates ───────────────────────────────────────────


@pytest.fixture
def currencies(db):
    for code in ("USD", "NZD"):
        Currency.objects.update_or_create(
            code=code,
            defaults={"name": code, "symbol": code, "decimal_places": 2, "is_active": True},
        )


def test_refreshing_rates_stores_what_the_service_returned(currencies, monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"base": "USD", "date": "2026-09-15", "rates": {"NZD": 1.62}}

    monkeypatch.setattr(exchange_rates.requests, "get", lambda *a, **k: Response())

    assert "Stored 1 rates against USD." in run("refresh_exchange_rates")
    assert ExchangeRate.objects.get().rate == Decimal("1.620000")


def test_a_refresh_that_reads_nothing_leaves_the_rates_on_file_and_says_so(currencies, monkeypatch):
    def unreachable(*args, **kwargs):
        raise RuntimeError("the network is down")

    monkeypatch.setattr(exchange_rates.requests, "get", unreachable)

    assert "No rates were stored" in run("refresh_exchange_rates")
    assert not ExchangeRate.objects.exists()


# ── issue_monthly_bills ──────────────────────────────────────────────


@pytest.fixture
def billable(db, settings, currencies):
    settings.PLATFORM_WORKSPACE_SLUG = PLATFORM_SLUG
    platform = Workspace.objects.create(name="Management", slug=PLATFORM_SLUG, is_active=True)
    Settings.objects.update_or_create(
        workspace=platform, defaults={"default_currency": "USD", "country": "NZ"}
    )
    shop = Workspace.objects.create(name="Corner Shop", slug="corner-cmd", is_active=True)
    Settings.objects.update_or_create(
        workspace=shop, defaults={"default_currency": "NZD", "country": "NZ"}
    )
    ownership.assign_workspace_owner(
        shop, User.objects.create_user(username="cmd-owner", password="x")
    )
    ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code="USD"),
        to_currency=Currency.objects.get(code="NZD"),
        effective_date=timezone.now().date() - timedelta(days=1),
        rate=Decimal("1.60"),
    )
    MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("1"), unit_size=1, margin=Decimal("0"),
        effective_from=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
    )
    usage.record_usage(shop, METER, 10, at=datetime(2026, 8, 5, tzinfo=datetime_timezone.utc))
    return shop


def test_issuing_a_month_s_bills_writes_them(billable):
    output = run("issue_monthly_bills", "--month", "2026-08")

    assert "1 invoices issued" in output
    assert Invoice.all_objects.get().invoice_number == f"PLAT-{billable.id}-202608"


def test_a_dry_run_prints_the_bill_and_writes_nothing(billable):
    output = run("issue_monthly_bills", "--month", "2026-08", "--dry-run")

    assert "Dry run" in output
    assert METER in output
    assert not Invoice.all_objects.exists()


def test_a_month_that_is_not_a_month_is_refused(billable):
    with pytest.raises(CommandError):
        call_command("issue_monthly_bills", "--month", "August")


def test_a_deployment_with_no_management_workspace_is_told_what_to_set(billable, settings):
    settings.PLATFORM_WORKSPACE_SLUG = ""

    with pytest.raises(CommandError) as refused:
        call_command("issue_monthly_bills", "--month", "2026-08")

    assert "PLATFORM_WORKSPACE_SLUG" in str(refused.value)

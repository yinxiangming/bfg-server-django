"""Getting a workspace an add-on it does not have yet.

Free add-ons are entitled and switched on at once; priced ones are billed for and
write nothing until the bill is paid. These cover both, what each is refused for,
and the bill's own life: its number, what it stops while it is unpaid, and the
first period paying it buys.

They also cover the two priced add-ons that are switched on before any bill — one
on trial, one there was no exchange rate to bill at — and what a console is told
an add-on would cost this workspace.

Manifests are faked, as in ``test_console_workspaces``.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.extensions import registry
from bfg.common.extensions.manifest import PRICING_CORE, ExtensionManifest, Prerequisite
from bfg.common.models import (
    Settings,
    StaffMember,
    StaffRole,
    Workspace,
    WorkspaceExtension,
)
from bfg.core.events import global_dispatcher
from bfg.finance.models import Currency, ExchangeRate, Invoice, TaxRate
from bfg.finance.services import InvoiceService
from bfg.platform import handlers
from bfg.platform.models import WorkspaceEntitlement, WorkspacePlatformProfile
from bfg.platform.services import acquisitions, billing, entitlements, ownership, renewals, usage
from bfg.platform.services.provision_service import suspend_workspace
from bfg.shop.models import SubscriptionPlan

User = get_user_model()
pytestmark = pytest.mark.django_db

PLATFORM_SLUG = "management"
CONSOLE = "/api/v1/platform/console/workspaces/"
KEY = "reviews"
# A plan priced in the management workspace's currency, and what it comes to on a
# New Zealand workspace's bill: 49 US dollars at 1.60, plus 15% on top.
PLAN_PRICE = Decimal("49")
BILLED = Decimal("78.40")
GST_ON_IT = Decimal("11.76")
# Forty characters, which leaves a bill for it no room inside the fifty an invoice
# number holds.
LONG_KEY = "a" * 40
# What a plan that opens with a free month carries.
TRIAL_DAYS = 30

MANIFESTS = {
    # Two add-ons, so that one workspace's bills for each can be told apart.
    "reviews": ExtensionManifest(key="reviews", name="Reviews", app_label="reviews_app"),
    "maps": ExtensionManifest(key="maps", name="Maps", app_label="maps_app"),
    # An add-on that cannot be switched on until another one is.
    "review_insights": ExtensionManifest(
        key="review_insights", name="Review insights", requires=("reviews",), app_label="insights_app",
    ),
    # An add-on nothing on this deployment can meet the conditions for.
    "gated": ExtensionManifest(
        key="gated",
        name="Gated",
        app_label="gated_app",
        prerequisites=(
            Prerequisite(code="never", message="Not on this deployment.", check=lambda workspace: False),
        ),
    ),
    # Part of the base plan rather than something sold separately.
    "notes": ExtensionManifest(
        key="notes", name="Notes", pricing=PRICING_CORE, app_label="notes_app",
    ),
    # A key long enough that a bill for it could not be numbered.
    LONG_KEY: ExtensionManifest(key=LONG_KEY, name="Long", app_label="long_app"),
}


# ── The deployment ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fake_manifests(monkeypatch):
    monkeypatch.setattr(registry, "_discover", lambda: dict(MANIFESTS))
    registry.reset_cache()
    cache.clear()
    yield
    registry.reset_cache()
    cache.clear()


@pytest.fixture(autouse=True)
def sells_extensions(settings):
    """A deployment that sells add-ons, which is the only kind that acquires one."""
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = PLATFORM_SLUG
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = (
        "bfg.platform.services.entitlements.entitlement_check"
    )


@pytest.fixture
def currencies(db):
    for code in ("USD", "NZD"):
        Currency.objects.update_or_create(
            code=code,
            defaults={"name": code, "symbol": code, "decimal_places": 2, "is_active": True},
        )


@pytest.fixture
def rate(currencies):
    """1 US dollar is 1.60 New Zealand dollars, published yesterday."""
    return ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code="USD"),
        to_currency=Currency.objects.get(code="NZD"),
        effective_date=timezone.now().date() - timedelta(days=1),
        rate=Decimal("1.60"),
    )


@pytest.fixture
def platform(db):
    """The workspace that sells, priced in US dollars."""
    workspace = Workspace.objects.create(name="Management", slug=PLATFORM_SLUG, is_active=True)
    _settings(workspace, "USD", "NZ")
    TaxRate.objects.create(
        workspace=workspace, name="GST", rate=Decimal("15.00"), country="NZ", is_active=True
    )
    return workspace


@pytest.fixture
def shop(platform):
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
def operator(platform):
    return _join(platform, _user("operator"), "admin")


@pytest.fixture
def plan(platform):
    return _plan(platform, KEY, PLAN_PRICE)


@pytest.fixture
def free_plan(platform):
    return _plan(platform, KEY, Decimal("0"))


@pytest.fixture
def trial_plan(platform):
    """The same price, after a month of it for nothing."""
    return _plan(platform, KEY, PLAN_PRICE, trial_period_days=TRIAL_DAYS)


def _plan(workspace, code, price, **fields):
    return SubscriptionPlan.objects.create(
        workspace=workspace, name=f"{code or 'Base'} plan", code=code, price=price, **fields
    )


def _settings(workspace, currency, country):
    row, _ = Settings.objects.update_or_create(
        workspace=workspace, defaults={"default_currency": currency, "country": country}
    )
    return row


def _user(username):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x"
    )


def _join(workspace, user, role_code):
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code=role_code, defaults={"name": role_code}
    )
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


# ── Asking ───────────────────────────────────────────────────────────


def acquire(user, workspace, key=KEY):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(f"{CONSOLE}{workspace.id}/extensions/{key}/acquire/", {}, format="json")


def detail(user, workspace):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.get(f"{CONSOLE}{workspace.id}/")


def extensions_of(response):
    return {row["key"]: row for row in response.data["extensions"]}


def _entitlements(workspace, key=KEY):
    return list(
        WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key).order_by("id")
    )


def _bills(workspace):
    return sorted(
        Invoice.all_objects.filter(
            invoice_number__startswith=billing.invoice_number_prefix(workspace.pk)
        ).values_list("invoice_number", flat=True)
    )


def _entitle(workspace, key=KEY, **fields):
    fields.setdefault("status", WorkspaceEntitlement.STATUS_ACTIVE)
    fields.setdefault("source", WorkspaceEntitlement.SOURCE_PURCHASED)
    return WorkspaceEntitlement.all_objects.create(workspace=workspace, key=key, **fields)


def _held_before(workspace, key=KEY):
    """A row saying the workspace has had this add-on, and has it no longer."""
    return _entitle(
        workspace,
        key,
        status=WorkspaceEntitlement.STATUS_ENDED,
        current_period_end=timezone.now() - timedelta(days=90),
    )


def _publish_rate():
    """Today's rate arriving, as the daily refresh brings it."""
    return ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code="USD"),
        to_currency=Currency.objects.get(code="NZD"),
        effective_date=timezone.now().date(),
        rate=Decimal("1.60"),
    )


def _price_of(user, workspace, key=KEY):
    return extensions_of(detail(user, workspace))[key]["price"]


# ── What it says no to ───────────────────────────────────────────────


def test_an_add_on_the_workspace_already_holds_is_refused(operator, shop, plan, rate):
    _entitle(shop)

    response = acquire(operator, shop)

    assert response.status_code == 400
    assert response.data["code"] == acquisitions.ALREADY_ENTITLED
    assert not Invoice.all_objects.exists()


def test_an_extension_that_is_part_of_the_base_plan_is_not_acquired_separately(
    operator, shop, platform, rate
):
    """It is included, so there is nothing to buy — even where a plan names it."""
    _plan(platform, "notes", PLAN_PRICE)

    response = acquire(operator, shop, key="notes")

    assert response.status_code == 400
    assert response.data["code"] == acquisitions.NOT_AN_ADDON
    assert not Invoice.all_objects.exists()
    assert _entitlements(shop, "notes") == []


def test_an_add_on_this_deployment_has_never_priced_is_refused(operator, shop, rate):
    """A missing plan is a deployment that has not priced it, not a free add-on."""
    response = acquire(operator, shop)

    assert response.status_code == 400
    assert response.data["code"] == acquisitions.NO_PLAN
    assert KEY in response.data["detail"]
    assert _entitlements(shop) == []


def test_a_key_no_app_declares_is_not_found(operator, shop, rate):
    response = acquire(operator, shop, key="nothing_here")

    assert response.status_code == 404
    assert response.data["code"] == "unknown_extension"


def test_a_plan_that_has_been_retired_no_longer_prices_the_add_on(operator, shop, platform, rate):
    _plan(platform, KEY, PLAN_PRICE, is_active=False)

    response = acquire(operator, shop)

    assert response.status_code == 400
    assert response.data["code"] == acquisitions.NO_PLAN


def test_an_add_on_whose_key_leaves_no_room_for_a_number_is_refused(
    operator, shop, owner, platform, rate
):
    """Refused rather than truncated: a number that cannot be read back buys nothing."""
    _plan(platform, LONG_KEY, PLAN_PRICE)

    response = acquire(operator, shop, key=LONG_KEY)

    assert response.status_code == 400
    assert response.data["code"] == acquisitions.KEY_TOO_LONG
    assert not Invoice.all_objects.exists()


def test_a_workspace_with_no_owner_cannot_be_billed(operator, shop, plan, rate):
    """There is nobody to make the bill out to, which is the deployment's to fix."""
    response = acquire(operator, shop)

    assert response.status_code == 400
    assert response.data["code"] == acquisitions.NO_OWNER
    assert not Invoice.all_objects.exists()


# ── A bill that could not be written today ───────────────────────────


def test_an_add_on_is_switched_on_when_there_is_no_rate_to_bill_it_at(
    operator, shop, owner, plan, currencies
):
    """A rate the deployment has not read yet is not the workspace's to wait for."""
    response = acquire(operator, shop)

    assert response.status_code == 200
    assert response.data["entitled"] is True
    assert response.data["billed_later"] is True
    assert response.data["invoice"] is None
    assert not Invoice.all_objects.exists()
    assert response.data["extension"]["status"] == WorkspaceExtension.STATUS_ACTIVE
    assert response.data["extension"]["available"] is True


def test_the_period_written_without_a_bill_is_a_bought_month(
    operator, shop, owner, plan, currencies
):
    """So that the run that bills every other month prices this one the same way."""
    acquire(operator, shop)

    row, = _entitlements(shop)
    assert row.source == WorkspaceEntitlement.SOURCE_PURCHASED
    assert row.plan_id == plan.pk
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE
    assert row.current_period_end == entitlements.add_months(row.starts_at, 1)


def test_the_month_nobody_could_bill_for_is_charged_by_the_monthly_run(
    operator, shop, owner, plan, currencies
):
    """What "billed later" comes to: the line a renewal of it would have made."""
    acquire(operator, shop)
    row, = _entitlements(shop)
    _publish_rate()

    entry, = billing.issue_monthly_bills(month=row.current_period_end.date())

    assert entry["issued"] is True
    charged = entry["lines"][0]
    assert charged["subtotal"] == BILLED
    assert KEY in charged["description"]


# ── An add-on with a trial ───────────────────────────────────────────


def test_a_plan_with_a_trial_is_switched_on_without_a_bill(
    operator, shop, owner, trial_plan, rate
):
    response = acquire(operator, shop)

    assert response.status_code == 200
    assert response.data["entitled"] is True
    assert response.data["trial_days"] == TRIAL_DAYS
    assert response.data["invoice"] is None
    assert not Invoice.all_objects.exists()
    assert response.data["extension"]["available"] is True


def test_the_trial_runs_for_the_days_the_plan_names(operator, shop, owner, trial_plan, rate):
    """And is a bought period, so it falls due and is billed like any other."""
    acquire(operator, shop)

    row, = _entitlements(shop)
    assert row.source == WorkspaceEntitlement.SOURCE_PURCHASED
    assert row.plan_id == trial_plan.pk
    assert row.current_period_end == row.starts_at + timedelta(days=TRIAL_DAYS)


def test_a_trial_is_had_once_however_often_the_add_on_lapses(
    operator, shop, owner, trial_plan, rate
):
    """One that came round with every lapse would be a way of never paying at all."""
    _held_before(shop)

    response = acquire(operator, shop)

    assert response.data["trial_days"] == 0
    assert response.data["invoice"]["subtotal"] == str(BILLED)


def test_a_trial_is_no_reason_to_give_away_an_add_on_the_deployment_prices(
    operator, shop, owner, trial_plan, rate
):
    """The trial ends where any other period does, and the month after it is billed."""
    acquire(operator, shop)
    row, = _entitlements(shop)

    entry, = billing.issue_monthly_bills(month=row.current_period_end.date())

    assert entry["lines"][0]["subtotal"] == BILLED


# ── What a console is told an add-on costs ───────────────────────────


def test_the_console_says_what_an_add_on_costs_in_the_workspace_s_own_currency(
    operator, shop, plan, rate
):
    price = _price_of(operator, shop)

    assert price["plan"] == plan.name
    assert price["amount"] == "49.00"
    assert price["currency"] == "USD"
    assert price["workspace_amount"] == str(BILLED)
    assert price["workspace_currency"] == "NZD"
    assert price["interval"] == "month"
    assert price["trial_days"] == 0


def test_a_price_is_still_shown_when_no_rate_has_been_stored(operator, shop, plan, currencies):
    """The deployment's own price is a better answer than no price at all."""
    price = _price_of(operator, shop)

    assert price["amount"] == "49.00"
    assert price["currency"] == "USD"
    assert price["workspace_amount"] is None


def test_an_extension_that_comes_with_the_base_plan_is_not_priced_on_its_own(
    operator, shop, platform, rate
):
    _plan(platform, acquisitions.PLAN_CODE_BASE_PLAN, PLAN_PRICE)

    assert _price_of(operator, shop, "notes") is None


def test_an_add_on_nobody_has_priced_carries_no_price(operator, shop, rate):
    assert _price_of(operator, shop) is None


def test_the_trial_a_console_shows_is_the_one_this_workspace_would_get(
    operator, shop, trial_plan, rate
):
    """Showing a trial to somebody who has already had it would be an offer we refuse."""
    assert _price_of(operator, shop)["trial_days"] == TRIAL_DAYS

    _held_before(shop)

    assert _price_of(operator, shop)["trial_days"] == 0


# ── An add-on that costs nothing ─────────────────────────────────────


def test_a_free_add_on_is_entitled_and_switched_on_at_once(operator, shop, free_plan):
    response = acquire(operator, shop)

    assert response.status_code == 200
    assert response.data["entitled"] is True
    assert response.data["invoice"] is None
    assert response.data["extension"]["status"] == WorkspaceExtension.STATUS_ACTIVE
    assert response.data["extension"]["available"] is True
    assert response.data["extension"]["entitled"] is True


def test_a_free_add_on_is_recorded_as_bought_and_never_expires(operator, shop, free_plan):
    acquire(operator, shop)

    row, = _entitlements(shop)
    assert row.source == WorkspaceEntitlement.SOURCE_PURCHASED
    assert row.plan_id == free_plan.pk
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE
    # Nothing to renew, so nothing to fall due.
    assert row.current_period_end is None
    assert entitlements.is_entitled(shop, KEY) is True


def test_a_free_add_on_is_never_billed_for(operator, shop, free_plan):
    acquire(operator, shop)

    assert not Invoice.all_objects.exists()


def test_who_switched_a_free_add_on_on_is_recorded(operator, shop, free_plan):
    acquire(operator, shop)

    record = WorkspaceExtension.all_objects.get(workspace=shop, key=KEY)
    assert record.status_changed_by_id == operator.pk


@pytest.mark.parametrize(
    "key, code",
    [("review_insights", "requires_inactive"), ("gated", "prerequisite_failed")],
)
def test_a_free_add_on_that_cannot_be_switched_on_leaves_no_entitlement_behind(
    operator, shop, platform, key, code
):
    """Both halves in one transaction: a refused activation undoes the entitlement."""
    _plan(platform, key, Decimal("0"))

    response = acquire(operator, shop, key=key)

    assert response.status_code == 400
    assert response.data["code"] == code
    assert _entitlements(shop, key) == []
    assert not WorkspaceExtension.all_objects.filter(
        workspace=shop, status=WorkspaceExtension.STATUS_ACTIVE
    ).exists()


# ── An add-on that costs something ───────────────────────────────────


def test_a_priced_add_on_is_billed_for_and_nothing_else_is_written(
    operator, shop, owner, plan, rate
):
    response = acquire(operator, shop)

    assert response.status_code == 200
    assert response.data["entitled"] is False
    # Not entitled and not switched on: the workspace has not paid yet.
    assert _entitlements(shop) == []
    assert not WorkspaceExtension.all_objects.filter(
        workspace=shop, status=WorkspaceExtension.STATUS_ACTIVE
    ).exists()
    assert response.data["extension"]["entitled"] is False
    assert response.data["extension"]["available"] is False


def test_the_bill_is_the_plan_s_price_in_the_workspace_s_own_currency_with_its_tax(
    operator, shop, owner, plan, rate
):
    invoice = acquire(operator, shop).data["invoice"]

    assert invoice["currency"] == "NZD"
    assert invoice["subtotal"] == str(BILLED)
    assert invoice["tax"] == str(GST_ON_IT)
    assert invoice["total"] == str(BILLED + GST_ON_IT)
    assert invoice["issued"] is True
    assert [item["subtotal"] for item in invoice["items"]] == [str(BILLED)]


def test_the_bill_is_issued_by_the_management_workspace_to_the_owner(
    operator, shop, owner, plan, rate
):
    acquire(operator, shop)

    written = Invoice.all_objects.get()
    assert written.workspace.slug == PLATFORM_SLUG
    assert written.customer.user_id == owner.pk
    assert written.status == billing.ISSUED_STATUS
    assert written.due_date == timezone.now().date() + timedelta(days=14)


def test_the_bill_s_number_says_which_workspace_bought_which_add_on(
    operator, shop, owner, plan, rate
):
    number = acquire(operator, shop).data["invoice"]["number"]

    assert number == f"PLAT-{shop.id}-ADD-{KEY}-1"
    assert billing.acquired_workspace_and_key(number) == (shop.id, KEY)
    # It bills no month, and must not be read as though it did.
    assert billing.billed_workspace_and_period(number) is None


def test_one_add_on_s_bill_is_not_taken_for_another_s(operator, shop, owner, platform, plan, rate):
    _plan(platform, "maps", PLAN_PRICE)

    acquire(operator, shop)
    acquire(operator, shop, key="maps")

    assert _bills(shop) == [f"PLAT-{shop.id}-ADD-maps-1", f"PLAT-{shop.id}-ADD-{KEY}-1"]


def test_asking_twice_hands_back_the_bill_that_is_already_outstanding(
    operator, shop, owner, plan, rate
):
    """A second click is somebody wondering, not somebody buying it twice."""
    first = acquire(operator, shop).data["invoice"]
    second = acquire(operator, shop).data["invoice"]

    assert second["id"] == first["id"]
    assert second["issued"] is False
    assert len(_bills(shop)) == 1


def test_a_bill_that_was_written_off_does_not_stand_in_the_way_of_buying_it_again(
    operator, shop, owner, plan, rate
):
    first = acquire(operator, shop).data["invoice"]
    Invoice.all_objects.filter(pk=first["id"]).update(status="cancelled")

    second = acquire(operator, shop).data["invoice"]

    assert second["number"] == f"PLAT-{shop.id}-ADD-{KEY}-2"
    assert second["issued"] is True


# ── What paying the bill buys ────────────────────────────────────────


def _pay(platform, invoice_id, capture):
    """What an operator does once the money has been reconciled."""
    invoice = Invoice.all_objects.get(pk=invoice_id)
    with capture(execute=True):
        InvoiceService(workspace=platform, user=None).mark_as_paid(invoice)
    return invoice


def test_paying_the_bill_writes_the_first_period(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    invoice = acquire(operator, shop).data["invoice"]

    paid = _pay(platform, invoice["id"], django_capture_on_commit_callbacks)

    row, = _entitlements(shop)
    assert row.source == WorkspaceEntitlement.SOURCE_PURCHASED
    assert row.plan_id == plan.pk
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE
    # A month from the day the bill was issued, so paying late buys no more than
    # paying on time.
    assert row.starts_at == billing.midnight(paid.issue_date)
    assert row.current_period_end == entitlements.add_months(row.starts_at, 1)
    assert entitlements.is_entitled(shop, KEY) is True


def test_the_period_is_anchored_to_the_bill_rather_than_to_when_the_money_arrived(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    invoice = acquire(operator, shop).data["invoice"]
    issued = timezone.now().date() - timedelta(days=10)
    Invoice.all_objects.filter(pk=invoice["id"]).update(issue_date=issued)

    _pay(platform, invoice["id"], django_capture_on_commit_callbacks)

    row, = _entitlements(shop)
    assert row.current_period_end == entitlements.add_months(billing.midnight(issued), 1)


def test_the_same_payment_reported_twice_buys_one_period(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    invoice = acquire(operator, shop).data["invoice"]
    _pay(platform, invoice["id"], django_capture_on_commit_callbacks)

    assert renewals.renew_for_invoice(invoice["id"]) == []
    assert len(_entitlements(shop)) == 1


def test_editing_a_paid_bill_later_does_not_buy_another_period(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    """The invoice editor's save is heard, and the period is already there."""
    invoice = acquire(operator, shop).data["invoice"]
    paid = _pay(platform, invoice["id"], django_capture_on_commit_callbacks)

    with django_capture_on_commit_callbacks(execute=True):
        paid.notes = "Reconciled against the 14th."
        paid.save()

    assert len(_entitlements(shop)) == 1


def test_the_status_written_straight_onto_the_row_is_heard(
    operator, shop, owner, plan, rate, django_capture_on_commit_callbacks
):
    """No service and no event: the model's own signal is the only way to hear it."""
    invoice = Invoice.all_objects.get(pk=acquire(operator, shop).data["invoice"]["id"])

    with django_capture_on_commit_callbacks(execute=True):
        invoice.status = "paid"
        invoice.paid_date = timezone.now().date()
        invoice.save()

    assert len(_entitlements(shop)) == 1


def test_a_completed_gateway_payment_is_heard(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    invoice = Invoice.all_objects.get(pk=acquire(operator, shop).data["invoice"]["id"])
    Invoice.all_objects.filter(pk=invoice.pk).update(status="paid")

    with django_capture_on_commit_callbacks(execute=True):
        global_dispatcher.dispatch(
            handlers.PAYMENT_COMPLETED,
            {"workspace": platform, "user": None, "data": {"payment": _Payment(invoice.pk)}},
        )

    assert len(_entitlements(shop)) == 1


class _Payment:
    def __init__(self, invoice_id):
        self.invoice_id = invoice_id


@pytest.mark.parametrize("status", ["sent", "draft", "cancelled"])
def test_a_bill_that_has_not_been_paid_buys_nothing(operator, shop, owner, plan, rate, status):
    invoice = acquire(operator, shop).data["invoice"]
    Invoice.all_objects.filter(pk=invoice["id"]).update(status=status)

    assert renewals.renew_for_invoice(invoice["id"]) == []
    assert _entitlements(shop) == []


def test_a_bill_whose_plan_has_gone_still_entitles_the_workspace_that_paid(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    """Money has changed hands; the hole in the pricing is not the payer's problem."""
    invoice = acquire(operator, shop).data["invoice"]
    SubscriptionPlan.objects.filter(pk=plan.pk).delete()

    _pay(platform, invoice["id"], django_capture_on_commit_callbacks)

    row, = _entitlements(shop)
    assert row.plan_id is None
    assert entitlements.is_entitled(shop, KEY) is True


def test_the_workspace_may_switch_the_add_on_on_once_the_bill_is_paid(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    """Buying it and using it are two steps: paying is what makes the second allowed."""
    invoice = acquire(operator, shop).data["invoice"]
    client = APIClient()
    client.force_authenticate(user=operator)
    switch_on = f"{CONSOLE}{shop.id}/extensions/{KEY}/activate/"

    refused = client.post(switch_on, {}, format="json")
    _pay(platform, invoice["id"], django_capture_on_commit_callbacks)
    allowed = client.post(switch_on, {}, format="json")

    assert (refused.status_code, refused.data["code"]) == (400, "not_entitled")
    assert allowed.status_code == 200
    assert allowed.data["entitled"] is True
    assert allowed.data["available"] is True


# ── What an unpaid bill stops ────────────────────────────────────────


def test_an_acquisition_bill_that_has_fallen_due_stops_metered_calls(
    operator, shop, owner, plan, rate
):
    """It is a real debt, and is counted as one by the rule that reads them all."""
    invoice = acquire(operator, shop).data["invoice"]
    assert usage.may_meter(shop) is True

    cache.clear()
    Invoice.all_objects.filter(pk=invoice["id"]).update(
        due_date=timezone.now().date() - timedelta(days=1)
    )

    assert usage.may_meter(shop) is False


def test_paying_it_lets_the_workspace_meter_again(
    operator, shop, owner, platform, plan, rate, django_capture_on_commit_callbacks
):
    invoice = acquire(operator, shop).data["invoice"]
    Invoice.all_objects.filter(pk=invoice["id"]).update(
        due_date=timezone.now().date() - timedelta(days=1)
    )
    assert usage.may_meter(shop) is False

    _pay(platform, invoice["id"], django_capture_on_commit_callbacks)

    assert usage.may_meter(shop) is True


# ── Reading a number back ────────────────────────────────────────────


@pytest.mark.parametrize(
    "number",
    [
        "",
        "INV-1001",
        "PLAT-7-202608",
        "PLAT-7-ADD",
        "PLAT-7-ADD-reviews",
        # No count on the end, a count that is not a number, and a key that is not
        # shaped like one.
        "PLAT-7-ADD-reviews-",
        "PLAT-7-ADD-reviews-x",
        "PLAT-7-ADD--1",
        "PLAT-7-ADD-Reviews-1",
        "PLAT-abc-ADD-reviews-1",
    ],
)
def test_a_number_that_is_not_an_acquisition_is_not_read_as_one(number):
    assert billing.acquired_workspace_and_key(number) is None


def test_both_shapes_are_recognised_as_this_deployment_s_own(db):
    assert billing.is_platform_bill("PLAT-7-202608") is True
    assert billing.is_platform_bill("PLAT-7-ADD-reviews-2") is True
    assert billing.is_platform_bill("INV-1001") is False


def test_the_bill_shows_up_in_the_workspace_s_own_list_of_them(operator, shop, owner, plan, rate):
    """It is one of the workspace's platform bills, and covers no month."""
    number = acquire(operator, shop).data["invoice"]["number"]

    client = APIClient()
    client.force_authenticate(user=operator)
    listed = client.get(f"{CONSOLE}{shop.id}/invoices/").data

    assert [row["number"] for row in listed] == [number]
    assert listed[0]["period"] == ""


# ── Which plan prices what ───────────────────────────────────────────


def test_a_plan_prices_the_add_on_whose_key_it_carries(platform, plan):
    assert acquisitions.plan_for(KEY) == plan
    assert acquisitions.plan_for("maps") is None


def test_the_base_plan_is_the_one_with_no_code(platform):
    """The same empty key an entitlement to the base plan itself is written under."""
    base = _plan(platform, WorkspaceEntitlement.KEY_BASE_PLAN, Decimal("40"))

    assert acquisitions.PLAN_CODE_BASE_PLAN == WorkspaceEntitlement.KEY_BASE_PLAN
    assert acquisitions.plan_for() == base


def test_a_workspace_s_own_plans_are_not_what_the_platform_sells(platform, shop):
    """A shop's plans are for its customers, whatever it happens to have called them."""
    _plan(shop, KEY, Decimal("5"))

    assert acquisitions.plan_for(KEY) is None


# ── Who may ask ──────────────────────────────────────────────────────


def test_the_owner_may_acquire_for_their_own_workspace(shop, owner, free_plan):
    assert acquire(owner, shop).status_code == 200


def test_a_platform_administrator_may_acquire_for_a_workspace_they_are_not_staff_of(
    operator, shop, free_plan
):
    assert acquire(operator, shop).status_code == 200


def test_the_owner_of_another_workspace_is_told_this_one_does_not_exist(shop, owner, free_plan):
    """Exactly what they are told about a workspace that is not there at all."""
    elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere", is_active=True)
    stranger = _user("stranger")
    ownership.assign_workspace_owner(elsewhere, stranger)

    response = acquire(stranger, shop)

    assert response.status_code == 404
    assert response.data["code"] == "workspace_not_found"
    assert _entitlements(shop) == []


def test_an_account_that_neither_administers_the_platform_nor_owns_anything_is_refused(
    shop, free_plan
):
    caller = _join(shop, _user("clerk"), "admin")

    assert acquire(caller, shop).status_code == 403
    assert _entitlements(shop) == []


def test_an_anonymous_caller_is_refused(shop, free_plan):
    response = APIClient().post(f"{CONSOLE}{shop.id}/extensions/{KEY}/acquire/", {}, format="json")

    assert response.status_code in (401, 403)
    assert _entitlements(shop) == []


def test_the_owner_of_a_suspended_workspace_only_reads_it(shop, owner, free_plan):
    WorkspacePlatformProfile.objects.get_or_create(workspace=shop)
    suspend_workspace(shop)

    response = acquire(owner, shop)

    assert response.status_code == 403
    assert response.data["code"] == "workspace_suspended"
    assert _entitlements(shop) == []


def test_a_platform_administrator_still_acquires_for_a_suspended_workspace(
    operator, shop, free_plan
):
    WorkspacePlatformProfile.objects.get_or_create(workspace=shop)
    suspend_workspace(shop)

    assert acquire(operator, shop).status_code == 200


# ── Telling "not bought" from "switched off" ─────────────────────────


def test_an_add_on_nobody_has_obtained_is_not_entitled(operator, shop):
    reviews = extensions_of(detail(operator, shop))[KEY]

    assert reviews["entitled"] is False
    assert reviews["available"] is False


def test_an_add_on_that_was_obtained_and_switched_off_is_still_entitled(operator, shop):
    """The console's cue to offer switching it back on rather than buying it again."""
    _entitle(shop)
    WorkspaceExtension.all_objects.create(
        workspace=shop, key=KEY, status=WorkspaceExtension.STATUS_INACTIVE
    )

    reviews = extensions_of(detail(operator, shop))[KEY]

    assert reviews["entitled"] is True
    assert reviews["available"] is False


def test_an_add_on_in_use_is_both(operator, shop):
    _entitle(shop)
    WorkspaceExtension.all_objects.create(
        workspace=shop, key=KEY, status=WorkspaceExtension.STATUS_ACTIVE
    )

    reviews = extensions_of(detail(operator, shop))[KEY]

    assert reviews["entitled"] is True
    assert reviews["available"] is True


def test_an_entitlement_that_has_run_out_is_no_longer_entitled(operator, shop):
    _entitle(
        shop,
        status=WorkspaceEntitlement.STATUS_ENDED,
        current_period_end=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
    )

    assert extensions_of(detail(operator, shop))[KEY]["entitled"] is False


def test_a_deployment_that_sells_nothing_entitles_every_extension(operator, shop, settings):
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = ""

    rows = extensions_of(detail(operator, shop))

    assert all(row["entitled"] for row in rows.values())


def test_an_extension_included_in_the_base_plan_is_always_entitled(operator, shop):
    assert extensions_of(detail(operator, shop))["notes"]["entitled"] is True


# ── The plan-pack hook ───────────────────────────────────────────────


def test_pack_obtain_gets_a_free_add_on_and_switches_it_on(free_plan, shop):
    """A pack should not stop at an add-on nobody is being sold."""
    assert acquisitions.pack_obtain(shop, registry.get_manifest(KEY)) is True
    assert entitlements.is_entitled(shop, KEY)


def test_pack_obtain_refuses_an_add_on_with_a_price(plan, shop):
    """A pack is not a purchase: nothing here may commit a workspace to a bill."""
    assert acquisitions.pack_obtain(shop, registry.get_manifest(KEY)) is False
    assert not entitlements.is_entitled(shop, KEY)


def test_pack_obtain_refuses_an_add_on_nothing_prices(shop):
    assert acquisitions.pack_obtain(shop, registry.get_manifest(KEY)) is False

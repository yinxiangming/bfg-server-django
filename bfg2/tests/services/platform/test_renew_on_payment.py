"""Paying a platform bill buys the next period of everything it renewed.

Issuing a bill records what was bought; nothing on that path writes a period
forward. These cover the other half: the payment event, what it renews, and what
it leaves alone.
"""

import logging
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from bfg.common.models import Customer, Settings, User, Workspace
from bfg.core.events import global_dispatcher
from bfg.finance.models import Currency, Invoice, PaymentGateway
from bfg.finance.services import InvoiceService, PaymentService
from bfg.platform import handlers
from bfg.platform.models import WorkspaceEntitlement
from bfg.platform.services import billing, entitlements, renewals, usage
from bfg.platform.services import platform_variables as variables
from bfg.shop.models import SubscriptionPlan

PLATFORM_SLUG = "management"
PERIOD = "202608"
# The period ends inside the month the bill is for, which is what makes it one of
# the renewals that bill charged for.
PERIOD_END = datetime(2026, 8, 20, 12, tzinfo=datetime_timezone.utc)
NEXT_PERIOD_END = datetime(2026, 9, 20, 12, tzinfo=datetime_timezone.utc)
KEY = "reviews"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_caches():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def platform_mode(settings):
    settings.PLATFORM_WORKSPACE_SLUG = PLATFORM_SLUG


@pytest.fixture
def currency(db):
    row, _ = Currency.objects.update_or_create(
        code="NZD",
        defaults={"name": "NZD", "symbol": "$", "decimal_places": 2, "is_active": True},
    )
    return row


@pytest.fixture
def platform(db):
    workspace = Workspace.objects.create(name="Management", slug=PLATFORM_SLUG, is_active=True)
    Settings.objects.update_or_create(
        workspace=workspace, defaults={"default_currency": "USD", "country": "NZ"}
    )
    return workspace


@pytest.fixture
def shop(platform):
    return Workspace.objects.create(name="Corner Shop", slug="corner-shop", is_active=True)


@pytest.fixture
def plan(platform):
    return SubscriptionPlan.objects.create(workspace=platform, name="Growth", price=Decimal("49"))


@pytest.fixture
def entitlement(shop, plan):
    return _entitlement(shop, plan)


def _entitlement(workspace, plan, **fields):
    fields.setdefault("key", KEY)
    fields.setdefault("source", WorkspaceEntitlement.SOURCE_PURCHASED)
    fields.setdefault("status", WorkspaceEntitlement.STATUS_ACTIVE)
    fields.setdefault("current_period_end", PERIOD_END)
    return WorkspaceEntitlement.all_objects.create(workspace=workspace, plan=plan, **fields)


def _invoice(platform, currency, number, *, status="paid", user=None):
    customer, _ = Customer.all_objects.get_or_create(
        workspace=platform,
        user=user or User.objects.create_user(username=f"payer-{number}", password="x"),
    )
    today = timezone.now().date()
    return Invoice.all_objects.create(
        workspace=platform,
        customer=customer,
        invoice_number=number,
        status=status,
        subtotal=Decimal("78.40"),
        tax=Decimal("11.76"),
        total=Decimal("90.16"),
        currency=currency,
        issue_date=today,
        due_date=today + timedelta(days=14),
        paid_date=today if status == "paid" else None,
    )


def _platform_bill(platform, currency, shop, **fields):
    return _invoice(platform, currency, f"PLAT-{shop.id}-{PERIOD}", **fields)


def _periods(workspace, key=KEY):
    return sorted(
        WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key)
        .values_list("current_period_end", flat=True)
    )


# ── What a paid bill renews ──────────────────────────────────────────


def test_paying_a_bill_writes_the_next_period_of_what_it_renewed(
    platform, shop, currency, entitlement, plan
):
    invoice = _platform_bill(platform, currency, shop)

    written = renewals.renew_for_invoice(invoice.pk)

    assert [row.current_period_end for row in written] == [NEXT_PERIOD_END]
    row = written[0]
    assert row.key == KEY
    assert row.plan_id == plan.pk
    assert row.source == WorkspaceEntitlement.SOURCE_PURCHASED
    assert row.status == WorkspaceEntitlement.STATUS_ACTIVE
    # The periods meet, so however long the bill took to pay leaves no gap.
    assert row.starts_at == PERIOD_END


def test_the_new_period_is_what_makes_the_workspace_entitled_again(
    platform, shop, currency, plan
):
    variables.set_variable("grace_days", 1, user=None, reason="test")
    ended = timezone.now() - timedelta(days=3)
    _entitlement(shop, plan, current_period_end=ended, status=WorkspaceEntitlement.STATUS_GRACE,
                 grace_until=ended + timedelta(days=1))
    assert entitlements.is_entitled(shop, KEY) is False

    renewals.renew_for_invoice(
        _invoice(platform, currency, f"PLAT-{shop.id}-{ended:%Y%m}").pk
    )

    assert entitlements.is_entitled(shop, KEY) is True


def test_the_row_that_was_waiting_for_the_money_is_settled_rather_than_left_in_grace(
    platform, shop, currency, plan
):
    row = _entitlement(
        shop, plan,
        status=WorkspaceEntitlement.STATUS_GRACE,
        grace_until=PERIOD_END + timedelta(days=14),
    )

    renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk)

    row.refresh_from_db()
    assert row.status == WorkspaceEntitlement.STATUS_ENDED
    assert row.ended_reason == renewals.RENEWED_REASON


def test_a_row_still_running_is_left_for_the_sweep_to_settle(
    platform, shop, currency, entitlement
):
    renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk)

    entitlement.refresh_from_db()
    assert entitlement.status == WorkspaceEntitlement.STATUS_ACTIVE
    assert entitlement.ended_reason == ""


def test_every_renewal_on_the_bill_gets_its_own_period(platform, shop, currency, plan):
    _entitlement(shop, plan)
    _entitlement(shop, plan, key="maps")

    written = renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk)

    assert sorted(row.key for row in written) == ["maps", KEY]


def test_a_period_that_ended_in_another_month_is_not_renewed_by_this_bill(
    platform, shop, currency, plan
):
    _entitlement(shop, plan, current_period_end=datetime(2026, 7, 20, 12, tzinfo=datetime_timezone.utc))

    assert renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk) == []


def test_an_entitlement_that_was_given_rather_than_bought_renews_nothing(
    platform, shop, currency, plan
):
    # It was not on the bill, so the payment did not buy it another month.
    _entitlement(shop, plan, source=WorkspaceEntitlement.SOURCE_GRANTED)

    assert renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk) == []


def test_a_period_end_on_the_last_day_of_a_month_is_clamped_to_the_next_month_s_length(
    platform, shop, currency, plan
):
    _entitlement(shop, plan, current_period_end=datetime(2026, 8, 31, 9, tzinfo=datetime_timezone.utc))

    written = renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk)

    assert written[0].current_period_end == datetime(2026, 9, 30, 9, tzinfo=datetime_timezone.utc)


# ── Being told twice ─────────────────────────────────────────────────


def test_the_same_payment_reported_twice_buys_one_period(
    platform, shop, currency, entitlement
):
    invoice = _platform_bill(platform, currency, shop)

    renewals.renew_for_invoice(invoice.pk)
    second = renewals.renew_for_invoice(invoice.pk)

    assert second == []
    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_a_period_that_is_already_on_file_is_not_written_a_second_time(
    platform, shop, currency, entitlement, plan
):
    """Nothing has to be remembered about the payment: the period is the record.

    A period written by hand — an operator sorting out a payment taken off the
    books — is as good as one written here, and the bill does not add another.
    """
    _entitlement(shop, plan, current_period_end=NEXT_PERIOD_END)

    assert renewals.renew_for_invoice(_platform_bill(platform, currency, shop).pk) == []
    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


# ── What is not renewed ──────────────────────────────────────────────


def test_a_workspace_s_own_invoice_is_not_a_platform_bill(shop, currency, entitlement):
    """An invoice a shop issued to one of its own customers renews nothing."""
    own = _invoice(shop, currency, f"PLAT-{shop.id}-{PERIOD}")

    assert renewals.renew_for_invoice(own.pk) == []
    assert _periods(shop) == [PERIOD_END]


def test_an_invoice_numbered_by_the_platform_workspace_for_its_own_customer_is_left_alone(
    platform, shop, currency, entitlement
):
    assert renewals.renew_for_invoice(_invoice(platform, currency, "INV-1001").pk) == []
    assert _periods(shop) == [PERIOD_END]


@pytest.mark.parametrize("number", ["PLAT-", "PLAT-abc-202608", "PLAT-7", "PLAT-7-2026", "PLAT-7-202613"])
def test_a_number_shaped_like_ours_that_nothing_issued_renews_nothing(
    platform, shop, currency, entitlement, number
):
    assert renewals.renew_for_invoice(_invoice(platform, currency, number).pk) == []


@pytest.mark.parametrize("status", ["sent", "draft", "overdue", "cancelled"])
def test_a_bill_that_is_not_paid_renews_nothing(platform, shop, currency, entitlement, status):
    invoice = _platform_bill(platform, currency, shop, status=status)

    assert renewals.renew_for_invoice(invoice.pk) == []
    assert _periods(shop) == [PERIOD_END]


def test_an_invoice_that_is_no_longer_there_is_not_an_error(platform, shop, currency):
    assert renewals.renew_for_invoice(99999) == []


def test_a_deployment_with_no_management_workspace_renews_nothing(
    settings, shop, currency, plan
):
    settings.PLATFORM_WORKSPACE_SLUG = ""
    _entitlement(shop, plan)

    assert renewals.renew_for_invoice(1) == []


def test_a_bill_with_no_entitlement_behind_it_is_logged_rather_than_raised(
    platform, shop, currency, caplog
):
    """A bill raised by hand has no renewal lines, so there is nothing to write."""
    invoice = _platform_bill(platform, currency, shop)

    with caplog.at_level(logging.INFO, logger=renewals.__name__):
        assert renewals.renew_for_invoice(invoice.pk) == []

    assert invoice.invoice_number in caplog.text
    assert "2026-08" in caplog.text


# ── Through the payment event ────────────────────────────────────────


def _complete(invoice_id, workspace):
    global_dispatcher.dispatch(
        handlers.PAYMENT_COMPLETED,
        {
            "workspace": workspace,
            "user": None,
            # Only the id is read, so the event carries whatever finance hands over.
            "data": {"payment": _Payment(invoice_id)},
        },
    )


class _Payment:
    def __init__(self, invoice_id):
        self.invoice_id = invoice_id


def _invoice_paid(invoice, workspace):
    global_dispatcher.dispatch(
        handlers.INVOICE_PAID,
        {"workspace": workspace, "user": None, "data": {"invoice": invoice}},
    )


def test_a_completed_payment_renews_what_its_bill_bought(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    invoice = _platform_bill(platform, currency, shop)

    with django_capture_on_commit_callbacks(execute=True):
        _complete(invoice.pk, platform)

    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_nothing_is_renewed_until_the_payment_has_committed(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """The invoice's own status is written in the transaction the event fires in."""
    invoice = _platform_bill(platform, currency, shop)

    with django_capture_on_commit_callbacks(execute=False) as queued:
        _complete(invoice.pk, platform)
        assert _periods(shop) == [PERIOD_END]

    assert len(queued) == 1


def test_a_payment_against_an_order_rather_than_a_bill_costs_nothing(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True) as queued:
        _complete(None, shop)

    assert queued == []
    assert _periods(shop) == [PERIOD_END]


def test_both_events_for_one_gateway_payment_still_buy_one_period(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """Settling an invoice through a gateway emits both, and both are listened for."""
    invoice = _platform_bill(platform, currency, shop)

    with django_capture_on_commit_callbacks(execute=True):
        _complete(invoice.pk, platform)
        _invoice_paid(invoice, platform)

    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_paying_a_bill_through_a_gateway_renews_it_end_to_end(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """The whole way through ``PaymentService``, rather than a dispatched event."""
    invoice = _platform_bill(platform, currency, shop, status="sent")
    gateway = PaymentGateway.objects.create(
        workspace=platform, name="Pay by transfer", gateway_type="pay_in_store",
        config={}, test_config={},
    )
    service = PaymentService(workspace=platform, user=None)
    payment = service.create_payment(
        invoice.customer, invoice.total, currency, gateway, invoice=invoice
    )

    with django_capture_on_commit_callbacks(execute=True):
        service.process_payment(payment, {"reference": "TT-1"}, manual_confirmation=True)

    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


# ── Money taken outside a gateway ────────────────────────────────────


def _mark_paid(platform, invoice):
    """What an operator does once a bank transfer has been reconciled."""
    InvoiceService(workspace=platform, user=None).mark_as_paid(invoice)


def test_marking_a_bill_paid_by_hand_renews_what_it_bought(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """A bank transfer has no payment row, so only ``invoice.paid`` reports it."""
    invoice = _platform_bill(platform, currency, shop, status="sent")

    with django_capture_on_commit_callbacks(execute=True):
        _mark_paid(platform, invoice)

    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_marking_the_same_bill_paid_twice_buys_one_period(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    invoice = _platform_bill(platform, currency, shop, status="sent")

    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            _mark_paid(platform, invoice)

    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_a_shop_marking_its_own_invoice_paid_renews_nothing(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    own = _invoice(shop, currency, f"PLAT-{shop.id}-{PERIOD}", status="sent")

    with django_capture_on_commit_callbacks(execute=True):
        InvoiceService(workspace=shop, user=None).mark_as_paid(own)

    assert _periods(shop) == [PERIOD_END]


def test_nothing_is_renewed_until_the_marking_has_committed(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    invoice = _platform_bill(platform, currency, shop, status="sent")

    with django_capture_on_commit_callbacks(execute=False) as queued:
        _mark_paid(platform, invoice)
        assert _periods(shop) == [PERIOD_END]

    # The row being saved and the service's own event each queue the renewal. How
    # many is not the point — that neither ran before the commit is.
    assert queued


# ── What paying unblocks ─────────────────────────────────────────────


def test_paying_lets_the_workspace_meter_again_without_waiting_for_the_cache(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """The cached answer is dropped, rather than the workspace waiting a minute."""
    invoice = _platform_bill(platform, currency, shop, status="sent")
    Invoice.all_objects.filter(pk=invoice.pk).update(
        due_date=timezone.now().date() - timedelta(days=1)
    )
    # Asked and cached before the money arrives, which is what a metered call does.
    assert usage.may_meter(shop) is False
    assert cache.get(billing.overdue_cache_key(shop.id)) is not None

    with django_capture_on_commit_callbacks(execute=True):
        _mark_paid(platform, invoice)

    assert usage.may_meter(shop) is True


def test_the_cached_answer_is_dropped_even_when_there_was_nothing_to_renew(
    platform, shop, currency, django_capture_on_commit_callbacks
):
    """What made it wrong was the bill being paid, not what the payment renewed."""
    invoice = _platform_bill(platform, currency, shop, status="sent")
    Invoice.all_objects.filter(pk=invoice.pk).update(
        due_date=timezone.now().date() - timedelta(days=1)
    )
    assert usage.may_meter(shop) is False

    with django_capture_on_commit_callbacks(execute=True):
        _mark_paid(platform, invoice)

    assert cache.get(billing.overdue_cache_key(shop.id)) is None
    assert usage.may_meter(shop) is True


def test_another_workspace_s_cached_answer_is_left_alone(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere", is_active=True)
    cache.set(billing.overdue_cache_key(elsewhere.id), 1, 60)

    with django_capture_on_commit_callbacks(execute=True):
        _mark_paid(platform, _platform_bill(platform, currency, shop, status="sent"))

    assert cache.get(billing.overdue_cache_key(elsewhere.id)) == 1


# ── The status written straight onto the row ─────────────────────────


def _save_as_paid(invoice):
    """What the invoice editor does: the status field, saved."""
    invoice.status = "paid"
    invoice.paid_date = timezone.now().date()
    invoice.save()


def test_writing_the_status_onto_the_row_renews_what_the_bill_bought(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """No service and no event: the model's own signal is the only way to hear it."""
    invoice = _platform_bill(platform, currency, shop, status="sent")

    with django_capture_on_commit_callbacks(execute=True):
        _save_as_paid(invoice)

    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_saving_a_paid_bill_again_does_not_buy_another_period(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """An unrelated edit of a paid bill re-runs the renewal, which writes nothing."""
    invoice = _platform_bill(platform, currency, shop, status="sent")

    with django_capture_on_commit_callbacks(execute=True):
        _save_as_paid(invoice)
    with django_capture_on_commit_callbacks(execute=True):
        invoice.notes = "Reconciled against the 14th."
        invoice.save()

    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_a_shop_saving_its_own_invoice_as_paid_renews_nothing(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    own = _invoice(shop, currency, f"PLAT-{shop.id}-{PERIOD}", status="sent")

    with django_capture_on_commit_callbacks(execute=True):
        _save_as_paid(own)

    assert _periods(shop) == [PERIOD_END]


@pytest.mark.parametrize("number, status", [
    # Not a platform number, whoever saved it: the overwhelming majority of the
    # invoices a deployment writes.
    ("INV-1001", "paid"),
    # A platform bill that has not been settled.
    ("PLAT-7-202608", "sent"),
])
def test_saying_no_costs_nothing_but_the_save_itself(
    platform, currency, django_assert_num_queries, number, status
):
    """This runs on every invoice every deployment saves, so it may not query."""
    invoice = _invoice(platform, currency, number, status=status)

    # One query: the UPDATE. The receiver reads the status and the number off the
    # instance it was handed and stops there.
    with django_assert_num_queries(1):
        invoice.notes = "Edited."
        invoice.save()


def test_a_queryset_update_sends_no_signal_and_renews_nothing(
    platform, shop, currency, entitlement, django_capture_on_commit_callbacks
):
    """Documented in ``handlers``; nothing in the library settles a bill this way."""
    invoice = _platform_bill(platform, currency, shop, status="sent")

    with django_capture_on_commit_callbacks(execute=True) as queued:
        Invoice.all_objects.filter(pk=invoice.pk).update(status="paid")

    assert queued == []
    assert _periods(shop) == [PERIOD_END]

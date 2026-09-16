"""Paying a platform bill from the console.

``POST /api/v1/platform/console/workspaces/{id}/invoices/{number}/pay/`` is the one
write on the console that a workspace whose plan has lapsed may still make, and the
only way an owner has of settling what they owe. It starts a payment through one of
the *management* workspace's gateways and hands back what the payer needs to finish;
it never settles one itself.

The thing these tests guard above all is that a bill is reachable only from the
workspace it bills. A platform invoice belongs to the management workspace, so its
number is the only thing tying it to a tenant — guessing a neighbour's number must
answer exactly as a number nobody holds.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.models import Customer, Settings, StaffMember, StaffRole, Workspace
from bfg.finance.models import Currency, Invoice, Payment, PaymentGateway
from bfg.platform.models import WorkspaceEntitlement
from bfg.platform.services import read_only
from bfg.platform.services.bill_payment import (
    INVOICE_ALREADY_PAID,
    INVOICE_CANCELLED,
    INVOICE_NOT_FOUND,
    INVOICE_NOTHING_TO_PAY,
    NO_PAYMENT_GATEWAY,
    PAYMENT_GATEWAY_NOT_FOUND,
    PAYMENT_IN_PROGRESS,
)
from bfg.platform.services.ownership import assign_workspace_owner
from bfg.shop.models import SubscriptionPlan

User = get_user_model()
pytestmark = pytest.mark.django_db

CONSOLE = "/api/v1/platform/console/workspaces/"
PLATFORM_SLUG = "management"
PERIOD = "202608"
# The entitlement's period ends inside the month the bill covers, which is what
# makes it one of the renewals that bill charged for.
PERIOD_END = datetime(2026, 8, 20, 12, tzinfo=datetime_timezone.utc)
NEXT_PERIOD_END = datetime(2026, 9, 20, 12, tzinfo=datetime_timezone.utc)
KEY = "reviews"


@pytest.fixture(autouse=True)
def clear_caches():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def platform_mode(settings):
    settings.PLATFORM_EMBEDDED = True
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
    workspace = Workspace.objects.create(name="Corner Shop", slug="corner-shop", is_active=True)
    Settings.objects.update_or_create(
        workspace=workspace, defaults={"default_currency": "NZD", "country": "NZ"}
    )
    return workspace


@pytest.fixture
def other_shop(platform):
    """A second tenant, with an owner of its own and a bill of its own."""
    return Workspace.objects.create(name="Other Shop", slug="other-shop", is_active=True)


@pytest.fixture
def owner(shop):
    user = User.objects.create_user(username="owner", email="owner@example.com", password="x")
    assign_workspace_owner(shop, user)
    return user


@pytest.fixture
def other_owner(other_shop):
    user = User.objects.create_user(username="other", email="other@example.com", password="x")
    assign_workspace_owner(other_shop, user)
    return user


@pytest.fixture
def operator(platform):
    """A platform administrator: active admin staff of the management workspace."""
    user = User.objects.create_user(username="operator", email="op@example.com", password="x")
    role, _ = StaffRole.objects.get_or_create(
        workspace=platform, code="admin", defaults={"name": "Admin"}
    )
    StaffMember.all_objects.create(workspace=platform, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def gateway(platform):
    """Something the management workspace can be paid through."""
    return PaymentGateway.objects.create(
        workspace=platform, name="Pay by transfer", gateway_type="bank_transfer",
        config={"account_name": "The Deployment", "account_number": "12-3456-7890123-00"},
        test_config={}, is_active=True,
    )


@pytest.fixture
def bill(platform, shop, currency):
    return _bill_for(platform, shop, currency)


def _bill_for(platform, workspace, currency, *, status="sent", total="115.00", user=None,
              period=PERIOD):
    """A platform bill for ``workspace``, made out to its owner as billing makes one."""
    from bfg.platform.services.ownership import workspace_owners

    payer = user or workspace_owners([workspace.pk]).get(workspace.pk)
    if payer is None:
        payer = User.objects.create_user(username=f"payer-{workspace.pk}", password="x")
    customer, _ = Customer.all_objects.get_or_create(workspace=platform, user=payer)
    today = timezone.now().date()
    total = Decimal(total)
    return Invoice.all_objects.create(
        workspace=platform,
        customer=customer,
        invoice_number=f"PLAT-{workspace.pk}-{period}",
        status=status,
        subtotal=total,
        tax=Decimal("0"),
        total=total,
        currency=currency,
        issue_date=today,
        due_date=today + timedelta(days=14),
        paid_date=today if status == "paid" else None,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _pay(user, workspace, number, **body):
    return _client(user).post(f"{CONSOLE}{workspace.pk}/invoices/{number}/pay/", body, format="json")


# ── Who may pay ──────────────────────────────────────────────────────


def test_the_owner_can_start_paying_their_own_bill(owner, shop, bill, gateway):
    response = _pay(owner, shop, bill.invoice_number)

    assert response.status_code == 201, response.data
    assert response.data["invoice"]["number"] == bill.invoice_number
    assert response.data["invoice"]["total"] == "115.00"
    assert response.data["payment"]["status"] == "pending"
    assert response.data["payment"]["amount"] == "115.00"
    assert response.data["payment"]["currency"] == "NZD"
    assert response.data["gateway"]["id"] == gateway.pk
    assert response.data["gateway"]["type"] == "bank_transfer"
    # What the payer has to act on: where to send the money.
    assert response.data["gateway"]["instructions"]["account_number"] == "12-3456-7890123-00"


def test_a_platform_administrator_can_pay_for_a_workspace(operator, shop, bill, gateway):
    response = _pay(operator, shop, bill.invoice_number)

    assert response.status_code == 201, response.data
    payment = Payment.all_objects.get(pk=response.data["payment"]["id"])
    # Raised against the bill's own customer — the owner — not against whoever
    # pressed the button, so it settles the debt that exists rather than a new one.
    assert payment.customer_id == bill.customer_id


def test_the_payment_belongs_to_the_management_workspace(owner, shop, bill, gateway, platform):
    response = _pay(owner, shop, bill.invoice_number)

    payment = Payment.all_objects.get(pk=response.data["payment"]["id"])
    assert payment.workspace_id == platform.pk
    assert payment.invoice_id == bill.pk
    assert payment.gateway_id == gateway.pk


def test_someone_who_runs_no_workspace_cannot_use_the_endpoint(shop, bill, gateway):
    stranger = User.objects.create_user(username="stranger", password="x")

    response = _pay(stranger, shop, bill.invoice_number)

    assert response.status_code == 403


def test_an_anonymous_caller_is_refused(shop, bill, gateway):
    response = APIClient().post(f"{CONSOLE}{shop.pk}/invoices/{bill.invoice_number}/pay/")

    assert response.status_code in (401, 403)


# ── One tenant cannot reach another's bill ───────────────────────────


def test_another_workspaces_owner_cannot_reach_the_workspace(other_owner, shop, bill, gateway):
    """The workspace is not theirs, so it is answered as one that does not exist."""
    response = _pay(other_owner, shop, bill.invoice_number)

    assert response.status_code == 404
    assert response.data["code"] == "workspace_not_found"


def test_an_owner_cannot_pay_a_neighbours_bill_through_their_own_workspace(
    owner, shop, other_shop, other_owner, currency, gateway
):
    """The guess this guards: name someone else's invoice under a workspace you own."""
    neighbour = _bill_for(gateway.workspace, other_shop, currency)

    response = _pay(owner, shop, neighbour.invoice_number)

    assert response.status_code == 404
    assert response.data["code"] == INVOICE_NOT_FOUND
    assert not Payment.all_objects.filter(invoice=neighbour).exists()


def test_a_number_that_only_starts_like_the_workspaces_own_is_not_its_bill(
    owner, shop, platform, currency, gateway
):
    """Workspace 1's prefix must not match workspace 11's invoices.

    The separator is the whole of what keeps them apart, so the bill this asks for
    is one belonging to a workspace whose id begins with this one's.
    """
    number = f"PLAT-{shop.pk}0-{PERIOD}"
    customer, _ = Customer.all_objects.get_or_create(workspace=platform, user=owner)
    today = timezone.now().date()
    Invoice.all_objects.create(
        workspace=platform, customer=customer, invoice_number=number, status="sent",
        subtotal=Decimal("50"), tax=Decimal("0"), total=Decimal("50"), currency=currency,
        issue_date=today, due_date=today + timedelta(days=14),
    )

    response = _pay(owner, shop, number)

    assert response.status_code == 404
    assert response.data["code"] == INVOICE_NOT_FOUND


def test_an_invoice_that_is_not_a_platform_bill_is_not_found(owner, shop, platform, currency, gateway):
    """A workspace's own invoice to one of its customers is not payable here."""
    customer, _ = Customer.all_objects.get_or_create(workspace=shop, user=owner)
    today = timezone.now().date()
    ordinary = Invoice.all_objects.create(
        workspace=shop, customer=customer, invoice_number="INV-0001", status="sent",
        subtotal=Decimal("10"), tax=Decimal("0"), total=Decimal("10"), currency=currency,
        issue_date=today, due_date=today + timedelta(days=7),
    )

    response = _pay(owner, shop, ordinary.invoice_number)

    assert response.status_code == 404
    assert response.data["code"] == INVOICE_NOT_FOUND
    ordinary.refresh_from_db()
    assert ordinary.status == "sent"


def test_a_bill_nobody_issued_is_not_found(owner, shop, gateway):
    response = _pay(owner, shop, f"PLAT-{shop.pk}-209901")

    assert response.status_code == 404
    assert response.data["code"] == INVOICE_NOT_FOUND


# ── Bills there is nothing to pay on ─────────────────────────────────


def test_a_settled_bill_is_refused_rather_than_paid_twice(owner, shop, platform, currency, gateway):
    paid = _bill_for(platform, shop, currency, status="paid")

    response = _pay(owner, shop, paid.invoice_number)

    assert response.status_code == 400
    assert response.data["code"] == INVOICE_ALREADY_PAID
    assert not Payment.all_objects.filter(invoice=paid).exists()


def test_a_cancelled_bill_is_refused(owner, shop, platform, currency, gateway):
    cancelled = _bill_for(platform, shop, currency, status="cancelled")

    response = _pay(owner, shop, cancelled.invoice_number)

    assert response.status_code == 400
    assert response.data["code"] == INVOICE_CANCELLED


def test_a_bill_that_comes_to_nothing_is_refused(owner, shop, platform, currency, gateway):
    """A month covered entirely by the trial credit is a record, not a debt."""
    nothing = _bill_for(platform, shop, currency, total="0.00")

    response = _pay(owner, shop, nothing.invoice_number)

    assert response.status_code == 400
    assert response.data["code"] == INVOICE_NOTHING_TO_PAY


# ── Gateways ─────────────────────────────────────────────────────────


def test_a_deployment_with_no_gateway_says_so(owner, shop, bill):
    response = _pay(owner, shop, bill.invoice_number)

    assert response.status_code == 400
    assert response.data["code"] == NO_PAYMENT_GATEWAY


def test_a_gateway_can_be_named(owner, shop, bill, gateway, platform):
    second = PaymentGateway.objects.create(
        workspace=platform, name="At the counter", gateway_type="pay_in_store",
        config={}, test_config={}, is_active=True,
    )

    response = _pay(owner, shop, bill.invoice_number, gateway=second.pk)

    assert response.status_code == 201, response.data
    assert response.data["gateway"]["id"] == second.pk


def test_a_gateway_of_another_workspace_cannot_be_named(owner, shop, bill, gateway):
    """Naming a tenant's own gateway would take the deployment's money into it."""
    theirs = PaymentGateway.objects.create(
        workspace=shop, name="Shop's own card processor", gateway_type="bank_transfer",
        config={}, test_config={}, is_active=True,
    )

    response = _pay(owner, shop, bill.invoice_number, gateway=theirs.pk)

    assert response.status_code == 400
    assert response.data["code"] == PAYMENT_GATEWAY_NOT_FOUND


def test_a_deployment_with_no_management_workspace_says_so(owner, shop, bill, gateway, settings):
    """Nothing issues platform bills there, so there is nobody to be paid.

    A deployment's own misconfiguration rather than anything the caller did, so
    it is answered as one: 503, not a 400 telling them their bill is wrong.
    """
    settings.PLATFORM_WORKSPACE_SLUG = "no-such-workspace"

    response = _pay(owner, shop, bill.invoice_number)

    assert response.status_code == 503
    assert response.data["code"] == "platform_workspace_missing"


def test_an_inactive_gateway_cannot_be_named(owner, shop, bill, gateway):
    gateway.is_active = False
    gateway.save(update_fields=["is_active"])

    response = _pay(owner, shop, bill.invoice_number)

    assert response.status_code == 400
    assert response.data["code"] == NO_PAYMENT_GATEWAY


# ── Asking twice ─────────────────────────────────────────────────────


def test_asking_twice_hands_back_the_same_attempt(owner, shop, bill, gateway):
    first = _pay(owner, shop, bill.invoice_number)
    second = _pay(owner, shop, bill.invoice_number)

    assert second.status_code == 201, second.data
    assert second.data["payment"]["id"] == first.data["payment"]["id"]
    assert Payment.all_objects.filter(invoice=bill).count() == 1


def test_a_second_gateway_while_one_attempt_is_under_way_is_refused(
    owner, shop, bill, gateway, platform
):
    second = PaymentGateway.objects.create(
        workspace=platform, name="At the counter", gateway_type="pay_in_store",
        config={}, test_config={}, is_active=True,
    )
    _pay(owner, shop, bill.invoice_number)

    response = _pay(owner, shop, bill.invoice_number, gateway=second.pk)

    assert response.status_code == 400
    assert response.data["code"] == PAYMENT_IN_PROGRESS
    assert Payment.all_objects.filter(invoice=bill).count() == 1


# ── Nothing is settled by asking ─────────────────────────────────────


def test_starting_a_payment_does_not_settle_the_bill(owner, shop, bill, gateway):
    """Money is never taken on the payer's word."""
    _pay(owner, shop, bill.invoice_number)

    bill.refresh_from_db()
    assert bill.status == "sent"
    assert bill.paid_date is None


def test_starting_a_payment_renews_nothing(owner, shop, bill, gateway, platform):
    plan = SubscriptionPlan.objects.create(workspace=platform, name="Growth", price=Decimal("49"))
    WorkspaceEntitlement.all_objects.create(
        workspace=shop, plan=plan, key=KEY,
        source=WorkspaceEntitlement.SOURCE_PURCHASED,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=PERIOD_END,
    )

    _pay(owner, shop, bill.invoice_number)

    assert _periods(shop) == [PERIOD_END]


# ── What settling one does ───────────────────────────────────────────


def _periods(workspace, key=KEY):
    return sorted(
        WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key)
        .values_list("current_period_end", flat=True)
    )


def test_settling_the_payment_renews_what_the_bill_charged_for(
    owner, shop, bill, gateway, platform, currency, django_capture_on_commit_callbacks
):
    """End to end: the console starts it, whoever reconciles it finishes it."""
    from bfg.finance.services import PaymentService

    plan = SubscriptionPlan.objects.create(workspace=platform, name="Growth", price=Decimal("49"))
    WorkspaceEntitlement.all_objects.create(
        workspace=shop, plan=plan, key=KEY,
        source=WorkspaceEntitlement.SOURCE_PURCHASED,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=PERIOD_END,
    )
    started = _pay(owner, shop, bill.invoice_number)
    payment = Payment.all_objects.get(pk=started.data["payment"]["id"])

    service = PaymentService(workspace=platform, user=None)
    with django_capture_on_commit_callbacks(execute=True):
        service.process_payment(payment, {"reference": "TT-1"}, manual_confirmation=True)

    bill.refresh_from_db()
    assert bill.status == "paid"
    assert _periods(shop) == [PERIOD_END, NEXT_PERIOD_END]


def test_settling_the_payment_lets_the_workspace_be_written_to_again(
    owner, shop, gateway, platform, currency, settings, django_capture_on_commit_callbacks
):
    """Paying is the way out of read-only mode, so the cached answer goes with it.

    Dated from today rather than from this module's fixed period: the workspace
    has to be genuinely past its grace before it pays and genuinely inside a
    period afterwards, and both of those are questions about now.
    """
    from bfg.finance.services import PaymentService

    settings.BFG_READ_ONLY_WHEN_UNENTITLED = True
    # Past the fourteen days of grace, so the plan has lapsed; near enough that
    # the month the payment buys has not itself run out.
    lapsed_on = timezone.now() - timedelta(days=20)
    plan = SubscriptionPlan.objects.create(workspace=platform, name="Growth", price=Decimal("49"))
    WorkspaceEntitlement.all_objects.create(
        workspace=shop, plan=plan, key=WorkspaceEntitlement.KEY_BASE_PLAN,
        source=WorkspaceEntitlement.SOURCE_PURCHASED,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end=lapsed_on,
    )
    bill = _bill_for(platform, shop, currency, period=f"{lapsed_on:%Y%m}")
    # Asked once so that the answer is cached, which is the state a workspace is
    # in at the moment it pays: it has just been refused a write.
    assert read_only.is_read_only(shop) is True

    started = _pay(owner, shop, bill.invoice_number)
    payment = Payment.all_objects.get(pk=started.data["payment"]["id"])
    service = PaymentService(workspace=platform, user=None)
    with django_capture_on_commit_callbacks(execute=True):
        service.process_payment(payment, {"reference": "TT-1"}, manual_confirmation=True)

    assert read_only.is_read_only(shop) is False


# ── The mark that keeps a lapsed workspace able to pay ───────────────


def test_paying_is_marked_as_allowed_while_a_workspace_is_read_only():
    from django.test import RequestFactory
    from django.urls import resolve

    from bfg.core.read_only import is_exempt

    path = f"{CONSOLE}1/invoices/PLAT-1-{PERIOD}/pay/"
    match = resolve(path)

    assert is_exempt(match.func, RequestFactory().post(path), match.kwargs) is True


def test_changing_an_extension_is_not_marked():
    """The mark is on paying alone, not on everything the console can do."""
    from django.test import RequestFactory
    from django.urls import resolve

    from bfg.core.read_only import is_exempt

    path = f"{CONSOLE}1/extensions/reviews/activate/"
    match = resolve(path)

    assert is_exempt(match.func, RequestFactory().post(path), match.kwargs) is False

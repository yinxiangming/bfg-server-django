"""The console's two read-only reports: a month of usage, and the bills for it.

Both sit on ``/api/v1/platform/console/workspaces/{id}/`` and are reached by the
same people the rest of the console is: a platform administrator reaches every
workspace, an owner the ones they own, and anybody else is answered as though the
workspace were not there.

Money and points come back as strings. JSON has no decimal, and a console that
added up a column of floats would show a total a cent out, so every number here is
asserted as the string it is written as.
"""

from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.extensions import registry
from bfg.common.extensions.manifest import ExtensionManifest
from bfg.common.models import Customer, Settings, StaffMember, StaffRole, Workspace
from bfg.finance.models import Currency, ExchangeRate, Invoice, InvoiceItem
from bfg.platform.models import MeterPrice, WorkspacePlatformProfile
from bfg.platform.services import platform_variables as variables
from bfg.platform.services import usage
from bfg.platform.services.console_billing import INVOICE_LIMIT
from bfg.platform.services.ownership import assign_workspace_owner

User = get_user_model()
pytestmark = pytest.mark.django_db

CONSOLE = "/api/v1/platform/console/workspaces/"
PLATFORM_SLUG = "management"
METER = "vendor.lookup"
OTHER_METER = "vendor.geocode"
NOT_FOUND = {"code": "workspace_not_found", "detail": "Workspace not found."}


def at(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=datetime_timezone.utc)


MANIFESTS = {
    "maps": ExtensionManifest(key="maps", name="Maps", meters=(METER,), app_label="maps_app"),
    "reviews": ExtensionManifest(key="reviews", name="Reviews", app_label="reviews_app"),
}


@pytest.fixture(autouse=True)
def clear_caches():
    """The platform variables, and the answer to whether anything is overdue."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def fake_manifests(monkeypatch):
    """Two deployed extensions, one of which declares a meter; as in the console tests."""
    monkeypatch.setattr(registry, "_discover", lambda: dict(MANIFESTS))
    registry.reset_cache()
    yield
    registry.reset_cache()


@pytest.fixture(autouse=True)
def platform_mode(settings):
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = PLATFORM_SLUG


@pytest.fixture
def currencies(db):
    for code, places in (("USD", 2), ("NZD", 2)):
        Currency.objects.update_or_create(
            code=code,
            defaults={"name": code, "symbol": code, "decimal_places": places, "is_active": True},
        )


@pytest.fixture
def rate(currencies):
    """One US dollar is 1.60 New Zealand dollars, published yesterday."""
    return ExchangeRate.objects.create(
        from_currency=Currency.objects.get(code="USD"),
        to_currency=Currency.objects.get(code="NZD"),
        effective_date=timezone.now().date() - timedelta(days=1),
        rate=Decimal("1.60"),
    )


@pytest.fixture
def platform(db):
    workspace = Workspace.objects.create(name="Management", slug=PLATFORM_SLUG, is_active=True)
    _settings(workspace, "USD")
    return workspace


@pytest.fixture
def shop(platform):
    workspace = Workspace.objects.create(name="Corner Shop", slug="corner-shop", is_active=True)
    _settings(workspace, "NZD")
    return workspace


@pytest.fixture
def owner(shop):
    user = User.objects.create_user(username="owner", email="owner@example.com", password="x")
    assign_workspace_owner(shop, user)
    return user


@pytest.fixture
def operator(platform):
    return _join(platform, _user("operator"), "admin")


@pytest.fixture
def price(db):
    """A point a call, so the points in a test are the calls in it."""
    return MeterPrice.objects.create(
        meter=METER, vendor_cost=Decimal("1"), unit_size=1,
        margin=Decimal("0"), effective_from=at(2026, 1, 1),
    )


def _settings(workspace, currency):
    row, _ = Settings.objects.update_or_create(
        workspace=workspace, defaults={"default_currency": currency, "country": "NZ"}
    )
    return row


def _user(username):
    return User.objects.create_user(username=username, email=f"{username}@example.com", password="x")


def _join(workspace, user, role_code):
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code=role_code, defaults={"name": role_code}
    )
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def usage_url(workspace_id, month=None):
    return f"{CONSOLE}{workspace_id}/usage/" + (f"?month={month}" if month else "")


def invoices_url(workspace_id):
    return f"{CONSOLE}{workspace_id}/invoices/"


def _bill(platform, shop, period, *, status="sent", due, total=Decimal("106.72"), items=(), number=None):
    customer, _ = Customer.all_objects.get_or_create(
        workspace=platform,
        user=User.objects.create_user(username=f"payer-{User.objects.count()}", password="x"),
    )
    invoice = Invoice.all_objects.create(
        workspace=platform,
        customer=customer,
        invoice_number=number or f"PLAT-{shop.id}-{period}",
        status=status,
        subtotal=Decimal("92.80"),
        tax=Decimal("13.92"),
        total=total,
        currency=Currency.objects.get(code="NZD"),
        issue_date=date(int(period[:4]), int(period[4:]), 1),
        due_date=due,
        paid_date=due if status == "paid" else None,
    )
    for description, unit_price in items:
        InvoiceItem.objects.create(
            invoice=invoice, description=description, quantity=Decimal("1"),
            unit_price=unit_price, subtotal=unit_price,
        )
    return invoice


# ── Who may read them ────────────────────────────────────────────────


def _both(client, workspace):
    return [client.get(usage_url(workspace.id)), client.get(invoices_url(workspace.id))]


def test_a_platform_administrator_reads_a_workspace_they_are_not_staff_of(
    operator, shop, rate, price
):
    assert [response.status_code for response in _both(_client(operator), shop)] == [200, 200]


def test_an_owner_reads_their_own_workspace(owner, shop, rate, price):
    assert [response.status_code for response in _both(_client(owner), shop)] == [200, 200]


def test_an_owner_of_another_workspace_is_answered_as_though_this_one_did_not_exist(
    shop, rate, price, platform
):
    elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere", is_active=True)
    stranger = _user("stranger")
    assign_workspace_owner(elsewhere, stranger)

    responses = _both(_client(stranger), shop)

    assert [response.status_code for response in responses] == [404, 404]
    assert [response.data for response in responses] == [NOT_FOUND, NOT_FOUND]


def test_staff_who_neither_own_nor_administer_are_refused(shop, rate, price):
    caller = _join(shop, _user("clerk"), "admin")

    assert [response.status_code for response in _both(_client(caller), shop)] == [403, 403]


def test_an_anonymous_caller_is_refused(shop, rate, price):
    assert all(
        response.status_code in (401, 403) for response in _both(_client(), shop)
    )


def test_a_suspended_workspace_is_still_read_by_its_owner(owner, shop, rate, price):
    """Changing a suspended workspace is refused; seeing what it owes is the point."""
    WorkspacePlatformProfile.objects.update_or_create(
        workspace=shop, defaults={"suspended_at": timezone.now()}
    )

    assert [response.status_code for response in _both(_client(owner), shop)] == [200, 200]


# ── The usage report ─────────────────────────────────────────────────


def test_the_month_is_totalled_by_meter_and_broken_down_by_day(operator, shop, rate, price):
    MeterPrice.objects.create(
        meter=OTHER_METER, vendor_cost=Decimal("2"), unit_size=1,
        margin=Decimal("0"), effective_from=at(2026, 1, 1),
    )
    usage.record_usage(shop, METER, 3, at=at(2026, 9, 1))
    usage.record_usage(shop, METER, 7, at=at(2026, 9, 3))
    usage.record_usage(shop, OTHER_METER, 6, at=at(2026, 9, 3))

    body = _client(operator).get(usage_url(shop.id, "2026-09")).data

    assert body["month"] == "2026-09"
    assert body["currency"] == "NZD"
    assert body["used_points"] == "22.00000000"
    # Heaviest meter first: twelve points of geocoding against ten of lookups.
    assert body["meters"] == [
        {"meter": OTHER_METER, "extension": None, "extension_name": None,
         "quantity": "6.0000", "points": "12.00000000", "amount": "19.20"},
        {"meter": METER, "extension": "maps", "extension_name": "Maps",
         "quantity": "10.0000", "points": "10.00000000", "amount": "16.00"},
    ]
    # Days ascending, and each day's meters heaviest first.
    assert body["days"] == [
        {
            "day": "2026-09-01",
            "points": "3.00000000",
            "meters": [
                {"meter": METER, "extension": "maps", "extension_name": "Maps",
                 "quantity": "3.0000", "points": "3.00000000"},
            ],
        },
        {
            "day": "2026-09-03",
            "points": "19.00000000",
            "meters": [
                # No manifest declares this one, so it belongs to the base platform.
                {"meter": OTHER_METER, "extension": None, "extension_name": None,
                 "quantity": "6.0000", "points": "12.00000000"},
                {"meter": METER, "extension": "maps", "extension_name": "Maps",
                 "quantity": "7.0000", "points": "7.00000000"},
            ],
        },
    ]


def test_the_extension_behind_a_meter_is_worked_out_once_for_the_whole_report(
    operator, shop, rate, price, monkeypatch
):
    """The manifests are walked once a meter, not once a line of the breakdown."""
    from bfg.platform.services import console_billing

    asked = []
    walk = console_billing.extension_for_meter
    monkeypatch.setattr(
        console_billing, "extension_for_meter", lambda name: asked.append(name) or walk(name)
    )
    for day in (1, 2, 3, 4):
        usage.record_usage(shop, METER, 1, at=at(2026, 9, day))

    _client(operator).get(usage_url(shop.id, "2026-09"))

    assert asked == [METER]


def test_the_cap_is_what_is_left_of_it(operator, shop, rate, price):
    usage.record_usage(shop, METER, 13, at=at(2026, 9, 2))

    body = _client(operator).get(usage_url(shop.id, "2026-09")).data

    assert body["cap_points"] == "20.00"
    assert body["remaining_points"] == "7.00000000"
    # Twenty-two dollars fifty-something is what thirteen points come to at 1.60.
    assert body["estimated_amount"] == "20.80"


def test_a_workspace_that_has_negotiated_its_own_cap_is_shown_that_one(
    operator, shop, rate, price
):
    WorkspacePlatformProfile.objects.create(
        workspace=shop, monthly_usage_cap_points=Decimal("250")
    )

    body = _client(operator).get(usage_url(shop.id, "2026-09")).data

    assert body["cap_points"] == "250.00"
    assert body["remaining_points"] == "250.00000000"


def test_what_is_left_never_reads_as_less_than_nothing(operator, shop, rate, price):
    variables.set_variable("monthly_usage_cap_points", Decimal("5"), user=None, reason="test")
    usage.record_usage(shop, METER, 9, at=at(2026, 9, 2))

    body = _client(operator).get(usage_url(shop.id, "2026-09")).data

    assert body["used_points"] == "9.00000000"
    assert body["remaining_points"] == "0.00000000"


def test_a_month_with_nothing_in_it_is_a_report_with_nothing_in_it(
    operator, shop, rate, price
):
    usage.record_usage(shop, METER, 4, at=at(2026, 8, 2))

    body = _client(operator).get(usage_url(shop.id, "2026-09")).data

    assert body["used_points"] == "0.00000000"
    assert body["remaining_points"] == "20.00000000"
    assert body["estimated_amount"] == "0.00"
    assert body["meters"] == []
    assert body["days"] == []
    assert body["overdue"] is False


def test_no_month_asked_for_is_this_one(operator, shop, rate, price):
    usage.record_usage(shop, METER, 2)

    body = _client(operator).get(usage_url(shop.id)).data

    assert body["month"] == f"{timezone.now():%Y-%m}"
    assert body["used_points"] == "2.00000000"


@pytest.mark.parametrize("month", ["september", "2026-13", "2026", "2026-09-01", "26-09"])
def test_a_month_that_cannot_be_read_is_refused_rather_than_taken_for_this_one(
    operator, shop, rate, price, month
):
    """Silently showing this month's numbers under another month's heading is worse."""
    response = _client(operator).get(usage_url(shop.id, month))

    assert response.status_code == 400
    assert response.data["code"] == "invalid_month"


def test_a_month_written_without_its_leading_zero_is_still_that_month(
    operator, shop, rate, price
):
    usage.record_usage(shop, METER, 2, at=at(2026, 9, 2))

    body = _client(operator).get(usage_url(shop.id, "2026-9")).data

    assert body["month"] == "2026-09"
    assert body["used_points"] == "2.00000000"


def test_nothing_is_converted_when_no_rate_for_the_pair_has_been_stored(
    operator, shop, currencies, price
):
    """An estimate at a rate nobody published is worse than no estimate."""
    usage.record_usage(shop, METER, 5, at=at(2026, 9, 2))

    body = _client(operator).get(usage_url(shop.id, "2026-09")).data

    assert body["estimated_amount"] is None
    assert body["meters"] == [
        {"meter": METER, "extension": "maps", "extension_name": "Maps",
         "quantity": "5.0000", "points": "5.00000000", "amount": None}
    ]
    # The points themselves do not depend on a rate, so they are still reported.
    assert body["used_points"] == "5.00000000"


def test_a_bill_past_its_due_date_is_reported_as_overdue(operator, shop, rate, price):
    _bill(Workspace.objects.get(slug=PLATFORM_SLUG), shop, "202608",
          due=timezone.now().date() - timedelta(days=1))

    assert _client(operator).get(usage_url(shop.id, "2026-09")).data["overdue"] is True


def test_one_workspace_s_usage_is_not_another_s(operator, shop, platform, rate, price):
    elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere", is_active=True)
    usage.record_usage(elsewhere, METER, 40, at=at(2026, 9, 2))
    usage.record_usage(shop, METER, 1, at=at(2026, 9, 2))

    assert _client(operator).get(usage_url(shop.id, "2026-09")).data["used_points"] == "1.00000000"


# ── The bills ────────────────────────────────────────────────────────


def test_a_bill_is_shown_with_the_lines_it_was_made_of(operator, shop, platform, rate):
    today = timezone.now().date()
    _bill(
        platform, shop, "202608",
        due=today + timedelta(days=14),
        items=(("Growth — reviews renewal", Decimal("78.40")),
               (f"{METER} — 10 metered units", Decimal("16.00"))),
    )

    body = _client(operator).get(invoices_url(shop.id)).data

    assert len(body) == 1
    entry = body[0]
    assert entry["number"] == f"PLAT-{shop.id}-202608"
    assert entry["period"] == "2026-08"
    assert entry["status"] == "sent"
    assert entry["overdue"] is False
    assert entry["paid_date"] is None
    assert entry["issue_date"] == "2026-08-01"
    assert entry["due_date"] == (today + timedelta(days=14)).isoformat()
    assert entry["currency"] == "NZD"
    assert (entry["subtotal"], entry["tax"], entry["total"]) == ("92.80", "13.92", "106.72")
    assert entry["items"] == [
        {"description": "Growth — reviews renewal", "quantity": "1.00",
         "unit_price": "78.40", "subtotal": "78.40"},
        {"description": f"{METER} — 10 metered units", "quantity": "1.00",
         "unit_price": "16.00", "subtotal": "16.00"},
    ]


def test_bills_come_back_newest_first(operator, shop, platform, rate):
    due = timezone.now().date() + timedelta(days=14)
    for period in ("202606", "202608", "202607"):
        _bill(platform, shop, period, due=due)

    numbers = [entry["period"] for entry in _client(operator).get(invoices_url(shop.id)).data]

    assert numbers == ["2026-08", "2026-07", "2026-06"]


def test_only_so_many_bills_are_listed(operator, shop, platform, rate):
    """Bounded rather than growing with the age of the account; the newest survive."""
    due = timezone.now().date() + timedelta(days=14)
    months = [(2025 + index // 12, index % 12 + 1) for index in range(INVOICE_LIMIT + 3)]
    for year, month in months:
        _bill(platform, shop, f"{year}{month:02d}", due=due)

    listed = _client(operator).get(invoices_url(shop.id)).data

    assert len(listed) == INVOICE_LIMIT
    newest = months[-1]
    assert listed[0]["period"] == f"{newest[0]}-{newest[1]:02d}"


def test_a_bill_that_is_late_and_unpaid_says_so(operator, shop, platform, rate):
    yesterday = timezone.now().date() - timedelta(days=1)
    _bill(platform, shop, "202608", due=yesterday)
    _bill(platform, shop, "202607", due=yesterday, status="paid")
    # A month covered entirely by the trial credit is a record, not a debt.
    _bill(platform, shop, "202606", due=yesterday, total=Decimal("0"))

    flags = {entry["period"]: entry["overdue"] for entry in
             _client(operator).get(invoices_url(shop.id)).data}

    assert flags == {"2026-08": True, "2026-07": False, "2026-06": False}


@pytest.mark.parametrize(
    "status, late",
    [("draft", True), ("sent", True), ("overdue", True), ("paid", False), ("cancelled", False)],
)
def test_which_statuses_a_passed_due_date_makes_late(
    operator, shop, platform, rate, status, late
):
    """Every status ``finance.Invoice`` has, and whether the flag can be raised on it."""
    _bill(platform, shop, "202608", due=timezone.now().date() - timedelta(days=1), status=status)

    entry, = _client(operator).get(invoices_url(shop.id)).data

    assert entry["status"] == status
    assert entry["overdue"] is late


def test_a_bill_still_within_its_due_date_is_not_late_whatever_its_status(
    operator, shop, platform, rate
):
    _bill(platform, shop, "202608", due=timezone.now().date() + timedelta(days=1), status="overdue")

    entry, = _client(operator).get(invoices_url(shop.id)).data

    # The status is not the flag: nothing in the library moves a bill into it.
    assert (entry["status"], entry["overdue"]) == ("overdue", False)


def test_another_workspace_s_bills_are_not_listed(operator, shop, platform, rate):
    due = timezone.now().date() + timedelta(days=14)
    elsewhere = Workspace.objects.create(name="Elsewhere", slug="elsewhere", is_active=True)
    _bill(platform, shop, "202608", due=due)
    _bill(platform, elsewhere, "202608", due=due)

    listed = _client(operator).get(invoices_url(shop.id)).data

    assert [entry["number"] for entry in listed] == [f"PLAT-{shop.id}-202608"]


def test_a_bill_a_workspace_numbered_for_itself_is_not_one_of_the_platform_s(
    operator, shop, platform, rate
):
    """A workspace picks its own invoice prefix, so one copying ours must not show up."""
    due = timezone.now().date() + timedelta(days=14)
    _bill(shop, shop, "202608", due=due)

    assert _client(operator).get(invoices_url(shop.id)).data == []


def test_a_workspace_that_has_never_been_billed_has_an_empty_list(operator, shop, rate):
    assert _client(operator).get(invoices_url(shop.id)).data == []

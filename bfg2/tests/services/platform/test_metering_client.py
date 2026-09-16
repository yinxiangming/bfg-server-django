"""``allowed`` before the call and ``meter`` after it, and what each does when something is wrong.

Manifests are faked, so nothing here depends on which apps a deployment installs.
"""

from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

import pytest
from django.core.cache import cache

from bfg.common.extensions import registry
from bfg.common.extensions import services as extension_services
from bfg.common.extensions.manifest import SCOPE_PLATFORM, ExtensionManifest
from bfg.common.models import Workspace, WorkspaceExtension
from bfg.platform import metering
from bfg.platform.models import MeterPrice, UsageRecord, WorkspacePlatformProfile
from bfg.platform.services import entitlements, usage

ADDON_METER = "vendor.lookup"
PLATFORM_METER = "assistant.tokens"
UNDECLARED_METER = "core.exports"

MANIFESTS = {
    "reviews": ExtensionManifest(
        key="reviews", name="Reviews", meters=(ADDON_METER,), app_label="reviews_app"
    ),
    "assistant": ExtensionManifest(
        key="assistant",
        name="Assistant",
        scope=SCOPE_PLATFORM,
        meters=(PLATFORM_METER,),
        app_label="assistant_app",
    ),
}


@pytest.fixture(autouse=True)
def forget_unpriced_meters():
    """``meter`` remembers which meters it has complained about, for an hour."""
    metering._unpriced_logged_at.clear()
    yield
    metering._unpriced_logged_at.clear()


@pytest.fixture(autouse=True)
def fake_manifests(monkeypatch):
    monkeypatch.setattr(registry, "_discover", lambda: dict(MANIFESTS))
    registry.reset_cache()
    extension_services._load_entitlement_check.cache_clear()
    cache.clear()
    yield
    registry.reset_cache()
    extension_services._load_entitlement_check.cache_clear()
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name="Metering", slug="metering-ws", is_active=True)


@pytest.fixture(autouse=True)
def prices(db):
    for meter in (ADDON_METER, PLATFORM_METER, UNDECLARED_METER):
        MeterPrice.objects.create(
            meter=meter,
            vendor_cost=Decimal("1"),
            unit_size=1,
            margin=Decimal("0"),
            effective_from=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
        )


def _switch_on(workspace, key):
    return WorkspaceExtension.all_objects.create(
        workspace=workspace, key=key, status=WorkspaceExtension.STATUS_ACTIVE
    )


# ── Asking first ─────────────────────────────────────────────────────


def test_a_meter_belongs_to_the_extension_that_declares_it(db):
    assert metering.extension_for_meter(ADDON_METER) == "reviews"
    assert metering.extension_for_meter(UNDECLARED_METER) is None


def test_a_workspace_using_the_extension_and_under_its_cap_may_spend(workspace):
    _switch_on(workspace, "reviews")

    assert metering.allowed(workspace, ADDON_METER) is True


def test_a_workspace_that_has_not_switched_the_extension_on_may_not(workspace):
    assert metering.allowed(workspace, ADDON_METER) is False


def test_an_extension_every_workspace_has_gates_nothing(workspace):
    assert metering.allowed(workspace, PLATFORM_METER) is True


def test_a_meter_no_extension_declares_is_part_of_the_base_platform(workspace):
    assert metering.allowed(workspace, UNDECLARED_METER) is True


def test_a_workspace_that_has_used_up_its_month_may_not_spend(workspace):
    WorkspacePlatformProfile.objects.create(workspace=workspace, monthly_usage_cap_points=Decimal("5"))
    _switch_on(workspace, "reviews")
    metering.meter(workspace, ADDON_METER, 5)

    assert metering.allowed(workspace, ADDON_METER) is False


def test_nothing_is_allowed_without_a_workspace(db):
    assert metering.allowed(None, PLATFORM_METER) is False


def test_allowed_does_not_answer_yes_when_it_cannot_tell(workspace, monkeypatch):
    def unreachable(*args, **kwargs):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(metering.usage, "may_meter", unreachable)

    with pytest.raises(RuntimeError):
        metering.allowed(workspace, PLATFORM_METER)


# ── Counting afterwards ──────────────────────────────────────────────


def test_metering_a_call_records_what_it_cost(workspace):
    record = metering.meter(workspace, PLATFORM_METER, 3)

    assert record.points == Decimal("3")
    assert usage.points_used(workspace) == Decimal("3")


def test_metering_an_unpriced_meter_is_logged_rather_than_raised(workspace, caplog):
    MeterPrice.objects.all().delete()

    assert metering.meter(workspace, PLATFORM_METER) is None
    assert not UsageRecord.all_objects.exists()
    assert "has no price" in caplog.text


def test_an_unpriced_meter_is_a_warning_without_a_stack_trace(workspace, caplog):
    # Wiring a meter up before pricing it is what every rollout looks like for a
    # while. An error with a traceback, on every call, would say something is
    # broken; what is true is that a price row is missing.
    MeterPrice.objects.all().delete()

    metering.meter(workspace, PLATFORM_METER)

    records = [record for record in caplog.records if "has no price" in record.getMessage()]
    assert [record.levelname for record in records] == ["WARNING"]
    assert records[0].exc_info is None


def test_an_unpriced_meter_is_mentioned_once_a_window_rather_than_once_a_call(workspace, caplog):
    MeterPrice.objects.all().delete()

    for _ in range(5):
        metering.meter(workspace, PLATFORM_METER)
    metering.meter(workspace, UNDECLARED_METER)

    said = [record.getMessage() for record in caplog.records if "has no price" in record.getMessage()]
    assert len(said) == 2
    assert PLATFORM_METER in said[0]
    # A different meter is a different gap and is worth saying on its own.
    assert UNDECLARED_METER in said[1]


def test_a_broken_database_does_not_break_the_call_that_was_already_made(workspace, monkeypatch, caplog):
    def unreachable(*args, **kwargs):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(metering.usage, "record_usage", unreachable)

    assert metering.meter(workspace, PLATFORM_METER) is None
    assert "Could not record" in caplog.text


# ── Wired up to the extension system ─────────────────────────────────


def test_a_deployment_can_point_the_extension_entitlement_check_at_the_table(workspace, settings):
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = "bfg.platform.services.entitlements.entitlement_check"
    _switch_on(workspace, "reviews")

    # The add-on is switched on, but nothing entitles the workspace to it.
    assert extension_services.is_available(workspace, "reviews") is False
    assert metering.allowed(workspace, ADDON_METER) is False
    # An extension in the base plan is unaffected.
    assert extension_services.is_available(workspace, "assistant") is True

    entitlements.grant(workspace, "reviews", reason="on the house")
    cache.clear()

    assert extension_services.is_available(workspace, "reviews") is True
    assert metering.allowed(workspace, ADDON_METER) is True

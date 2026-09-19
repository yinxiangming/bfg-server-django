from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, Workspace, WorkspaceDomain
from bfg.finance.models import Currency, ExchangeRate
from bfg.common.exceptions import WorkspaceCapacityUnavailable
from bfg.common.constants import get_default_currency_for_workspace
from bfg.common.services.workspace_service import WorkspaceService
from bfg.platform.models import (
    Cluster,
    PlatformAuditEvent,
    PlatformMeterPrice,
    PlatformMeterPriceRequest,
    WorkspaceMeterUsage,
    WorkspaceOperation,
    WorkspaceUsageCap,
)
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile
from bfg.platform.serializers.workspace import WorkspaceCreateSerializer
from bfg.platform.services.workspace_service import is_platform_admin
from bfg.platform.services.cluster_health_service import ClusterHealthProbeResult, cluster_health_url
from bfg.shop.services.batch_service import is_batch_management_enabled


User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/v1/platform/console/workspaces/",
    "/api/v1/platform/console/clusters/",
    "/api/v1/platform/console/audit-events/",
    "/api/v1/platform/console/variables/",
    "/api/v1/platform/console/meter-prices/",
    "/api/v1/platform/console/exchange-rates/",
])
def test_platform_console_refuses_authenticated_non_superusers(path):
    tenant_admin = User.objects.create_user(
        username="tenant-admin", password="secret", is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=tenant_admin)

    response = client.get(path)

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/v1/platform/console/workspaces/",
    "/api/v1/platform/console/clusters/",
    "/api/v1/platform/console/audit-events/",
    "/api/v1/platform/console/variables/",
    "/api/v1/platform/console/meter-prices/",
    "/api/v1/platform/console/exchange-rates/",
])
def test_platform_console_challenges_unauthenticated_requests(path):
    response = APIClient().get(path)

    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/v1/platform/console/workspaces/",
    "/api/v1/platform/console/clusters/",
    "/api/v1/platform/console/audit-events/",
    "/api/v1/platform/console/variables/",
    "/api/v1/platform/console/meter-prices/",
    "/api/v1/platform/console/exchange-rates/",
])
def test_platform_console_allows_django_superusers(path):
    superuser = User.objects.create_superuser(
        username="platform-root", password="secret", email="root@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.get(path)

    assert response.status_code == 200


@pytest.mark.django_db
def test_platform_workspace_inventory_is_paginated_and_filterable(settings):
    settings.PLATFORM_EMBEDDED = True
    superuser = User.objects.create_superuser(
        username="inventory-root", password="secret", email="inventory@example.test",
    )
    cluster = Cluster.objects.create(
        id="inventory-cluster", name="Inventory", region="apac",
        api_base_url="https://api.example.test", db_host="db.example.test",
        redis_url="rediss://private.example.test/0", s3_bucket="inventory",
    )
    active = _embedded_workspace_member(superuser, slug="inventory-active")
    active_second = _embedded_workspace_member(superuser, slug="inventory-active-second")
    suspended = _embedded_workspace_member(superuser, slug="inventory-suspended")
    inactive = _embedded_workspace_member(superuser, slug="inventory-inactive")
    for workspace in (active, active_second, suspended, inactive):
        profile = WorkspacePlatformProfile.objects.get(workspace=workspace)
        profile.cluster = cluster
        profile.save(update_fields=["cluster", "updated_at"])
    suspended_profile = WorkspacePlatformProfile.objects.get(workspace=suspended)
    from django.utils import timezone
    suspended_profile.suspended_at = timezone.now()
    suspended_profile.save(update_fields=["suspended_at", "updated_at"])
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])

    client = APIClient()
    client.force_authenticate(user=superuser)
    first = client.get("/api/v1/platform/console/workspaces/?page_size=1&status=active&cluster=inventory-cluster")

    assert first.status_code == 200
    assert first.data["count"] == 2
    assert len(first.data["results"]) == 1
    assert first.data["next"]
    second = client.get(first.data["next"])
    assert second.status_code == 200
    assert len(second.data["results"]) == 1
    assert {first.data["results"][0]["id"], second.data["results"][0]["id"]} == {active.id, active_second.id}
    assert second.data["next"] is None
    assert client.get("/api/v1/platform/console/workspaces/?status=unknown").status_code == 400


@pytest.mark.django_db
def test_platform_console_capability_is_not_granted_by_staff_flag():
    staff_user = User.objects.create_user(
        username="staff-only", password="secret", is_staff=True,
    )

    assert is_platform_admin(staff_user) is False
    assert is_platform_admin(User.objects.create_superuser(
        username="root-only", password="secret", email="root-only@example.test",
    )) is True


@pytest.mark.django_db
def test_workspace_membership_response_exposes_only_superuser_platform_access():
    staff_user = User.objects.create_user(
        username="platform-staff", password="secret", is_staff=True,
    )
    superuser = User.objects.create_superuser(
        username="platform-superuser", password="secret", email="superuser@example.test",
    )
    client = APIClient()

    client.force_authenticate(user=staff_user)
    staff_response = client.get("/api/v1/platform/workspaces/me/")
    client.force_authenticate(user=superuser)
    superuser_response = client.get("/api/v1/platform/workspaces/me/")

    assert staff_response.status_code == 200
    assert staff_response.data["is_platform_admin"] is False
    assert staff_response.data["is_platform_superuser"] is False
    assert superuser_response.status_code == 200
    assert superuser_response.data["is_platform_admin"] is True
    assert superuser_response.data["is_platform_superuser"] is True
    assert staff_response.data["platform_capabilities"] == {
        "cluster_management": False,
        "audit_log": False,
        "configuration": False,
        "exchange_rates": False,
    }
    assert superuser_response.data["platform_capabilities"] == {
        "cluster_management": True,
        "audit_log": True,
        "configuration": True,
        "exchange_rates": False,
    }


@pytest.mark.django_db
def test_superuser_can_change_typed_platform_variable_with_an_audit_reason():
    superuser = User.objects.create_superuser(
        username="variables-root", password="secret", email="variables@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    listed = client.get("/api/v1/platform/console/variables/")
    assert listed.status_code == 200
    assert {item["key"] for item in listed.data} == {"default_meter_margin", "default_usage_cap_points"}

    changed = client.patch(
        "/api/v1/platform/console/variables/default_meter_margin/",
        {"value": "0.35", "reason": "Vendor margin changed", "confirm": True}, format="json",
    )
    assert changed.status_code == 200
    assert changed.data["value"] == "0.35"
    assert changed.data["overridden"] is True
    assert changed.data["last_change"]["reason"] == "Vendor margin changed"
    assert PlatformAuditEvent.objects.filter(
        action="configuration.variable_updated", target_id="default_meter_margin",
    ).exists()
    refused = client.patch(
        "/api/v1/platform/console/variables/default_meter_margin/",
        {"value": "0.40", "reason": "Missing explicit confirmation"}, format="json",
    )
    assert refused.status_code == 400


@pytest.mark.django_db
def test_meter_prices_are_append_only_and_use_the_platform_margin():
    superuser = User.objects.create_superuser(
        username="meter-root", password="secret", email="meter@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    available = client.get("/api/v1/platform/console/meter-prices/available-meters/")
    assert available.status_code == 200
    assert available.data == {"meters": ["ai.agent_chat"]}

    first = client.post("/api/v1/platform/console/meter-prices/", {
        "meter": "ai.agent_chat", "vendor_cost": "10", "unit_size": "100", "margin": "0.25", "confirm": True,
    }, format="json", HTTP_X_IDEMPOTENCY_KEY="meter-price-first-0001")
    assert first.status_code == 201
    assert first.data["meter"] == "ai.agent_chat"
    assert first.data["in_force"] == first.data["prices"][0]["id"]
    assert first.data["prices"][0]["points_per_unit"] == "0.1250000000"

    second = client.post("/api/v1/platform/console/meter-prices/", {
        "meter": "ai.agent_chat", "vendor_cost": "12", "unit_size": "100", "confirm": True,
    }, format="json", HTTP_X_IDEMPOTENCY_KEY="meter-price-second-001")
    assert second.status_code == 201
    assert len(second.data["prices"]) == 2
    assert any(price["uses_default_margin"] for price in second.data["prices"])
    assert PlatformAuditEvent.objects.filter(action="configuration.meter_price_added", target_id="ai.agent_chat").count() == 2

    unknown = client.post("/api/v1/platform/console/meter-prices/", {
        "meter": "store.image", "vendor_cost": "1", "unit_size": "1", "confirm": True,
    }, format="json", HTTP_X_IDEMPOTENCY_KEY="meter-price-unknown-001")
    assert unknown.status_code == 400
    assert unknown.data["code"] == "unknown_runtime_meter"


@pytest.mark.django_db
def test_meter_price_is_rolled_back_when_its_audit_write_fails():
    superuser = User.objects.create_superuser(
        username="meter-audit-root", password="secret", email="meter-audit@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    with patch("bfg.platform.views.console_views.record_platform_audit", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            client.post("/api/v1/platform/console/meter-prices/", {
                "meter": "ai.agent_chat", "vendor_cost": "10", "unit_size": "100", "confirm": True,
            }, format="json", HTTP_X_IDEMPOTENCY_KEY="meter-price-audit-001")

    assert PlatformMeterPrice.objects.count() == 0
    assert PlatformMeterPriceRequest.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("path,payload", [
    ("/api/v1/platform/console/meter-prices/", {
        "meter": "ai.agent_chat", "vendor_cost": "1e100", "unit_size": "100", "confirm": True,
    }),
    ("/api/v1/platform/console/meter-prices/", {
        "meter": "ai.agent_chat", "vendor_cost": "1", "unit_size": True, "confirm": True,
    }),
    ("/api/v1/platform/console/exchange-rates/", {
        "from": "NZD", "to": "USD", "rate": "1e100", "confirm": True,
    }),
])
def test_platform_configuration_rejects_values_outside_model_precision(path, payload):
    superuser = User.objects.create_superuser(
        username=f"invalid-{len(payload)}-{path.split('/')[-2]}", password="secret", email=f"invalid-{len(payload)}@example.test",
    )
    Currency.objects.get_or_create(code="NZD", defaults={"name": "New Zealand Dollar", "symbol": "$", "is_active": True})
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "US$", "is_active": True})
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.post(path, payload, format="json", HTTP_X_IDEMPOTENCY_KEY="invalid-config-0001")

    assert response.status_code == 400


@pytest.mark.django_db
def test_meter_price_write_is_persistently_idempotent():
    superuser = User.objects.create_superuser(
        username="meter-idempotency-root", password="secret", email="meter-idempotency@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)
    payload = {
        "meter": "ai.agent_chat", "vendor_cost": "10", "unit_size": "100", "confirm": True,
    }

    missing_key = client.post("/api/v1/platform/console/meter-prices/", payload, format="json")
    assert missing_key.status_code == 400
    assert missing_key.data["code"] == "idempotency_key_required"

    first = client.post(
        "/api/v1/platform/console/meter-prices/", payload, format="json",
        HTTP_X_IDEMPOTENCY_KEY="meter-price-retry-001",
    )
    assert first.status_code == 201
    first_price_id = first.data["prices"][0]["id"]
    assert PlatformMeterPrice.objects.count() == 1
    assert PlatformMeterPriceRequest.objects.filter(
        created_by=superuser, idempotency_key="meter-price-retry-001", price_id=first_price_id,
    ).exists()

    replayed = client.post(
        "/api/v1/platform/console/meter-prices/", payload, format="json",
        HTTP_X_IDEMPOTENCY_KEY="meter-price-retry-001",
    )
    assert replayed.status_code == 200
    assert replayed["Idempotent-Replayed"] == "true"
    assert replayed.data["prices"][0]["id"] == first_price_id
    assert PlatformMeterPrice.objects.count() == 1
    assert PlatformAuditEvent.objects.filter(action="configuration.meter_price_added").count() == 1

    reused = client.post(
        "/api/v1/platform/console/meter-prices/",
        {**payload, "vendor_cost": "11"},
        format="json", HTTP_X_IDEMPOTENCY_KEY="meter-price-retry-001",
    )
    assert reused.status_code == 409
    assert reused.data["code"] == "idempotency_key_reused"
    assert PlatformMeterPrice.objects.count() == 1


@pytest.mark.django_db
def test_platform_console_missing_workspace_returns_404_instead_of_server_error():
    superuser = User.objects.create_superuser(
        username="missing-workspace-root", password="secret", email="missing-workspace@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.get("/api/v1/platform/console/workspaces/999999/usage-cap/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_public_health_endpoint_checks_database_without_authentication():
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200
    assert response.data == {"status": "ok"}


def test_cluster_health_probe_url_requires_an_explicit_https_host_allowlist(settings):
    class Target:
        api_base_url = "https://api.uat.example.test"

    settings.CLUSTER_HEALTH_ALLOWED_HOSTS = ["*.example.test"]
    assert cluster_health_url(Target()) == "https://api.uat.example.test/api/v1/health/"

    Target.api_base_url = "http://api.uat.example.test"
    with pytest.raises(ValueError):
        cluster_health_url(Target())

    Target.api_base_url = "https://169.254.169.254"
    with pytest.raises(ValueError):
        cluster_health_url(Target())


@pytest.mark.django_db
def test_cluster_health_check_is_superuser_only_and_audited(settings):
    settings.CLUSTER_HEALTH_ALLOWED_HOSTS = ["api.cluster.example.test"]
    superuser = User.objects.create_superuser(
        username="cluster-health-root", password="secret", email="cluster-health@example.test",
    )
    tenant_admin = User.objects.create_user(username="cluster-health-tenant", password="secret", is_staff=True)
    cluster = Cluster.objects.create(
        id="cluster-health", name="Cluster health", region="apac",
        api_base_url="https://api.cluster.example.test", db_host="db.example.test",
        redis_url="rediss://private.example.test/0", s3_bucket="cluster-health", max_workspaces=20,
    )
    client = APIClient()
    client.force_authenticate(user=tenant_admin)
    denied = client.post(
        f"/api/v1/platform/console/clusters/{cluster.id}/health-check/",
        {"confirm": True, "reason": "Routine health check"}, format="json",
    )
    assert denied.status_code == 403

    client.force_authenticate(user=superuser)
    with patch(
        "bfg.platform.views.console_views.probe_cluster_health",
        return_value=ClusterHealthProbeResult(health_status="healthy", http_status=200),
    ):
        response = client.post(
            f"/api/v1/platform/console/clusters/{cluster.id}/health-check/",
            {"confirm": True, "reason": "Routine health check"}, format="json",
        )

    assert response.status_code == 200
    assert response.data["health_status"] == "healthy"
    assert response.data["last_health_check"] is not None
    event = PlatformAuditEvent.objects.get(action="cluster.health_checked", target_id=cluster.id)
    assert event.after["health_status"] == "healthy"
    assert event.after["http_status"] == 200


@pytest.mark.django_db
def test_platform_superuser_can_read_monthly_workspace_usage_only():
    superuser = User.objects.create_superuser(
        username="usage-root", password="secret", email="usage@example.test",
    )
    tenant_admin = User.objects.create_user(
        username="usage-tenant", password="secret", is_staff=True,
    )
    workspace = Workspace.objects.create(name="Usage Workspace", slug="usage-workspace", is_active=True)
    price = PlatformMeterPrice.objects.create(
        meter="ai.agent_chat", vendor_cost=Decimal("1"), unit_size=1, margin=Decimal("0"),
    )
    image_price = PlatformMeterPrice.objects.create(
        meter="store.image", vendor_cost=Decimal("1"), unit_size=1, margin=Decimal("0"),
    )
    WorkspaceUsageCap.objects.create(workspace=workspace, cap_points=Decimal("10.0000"))
    september = date(2026, 9, 1)
    WorkspaceMeterUsage.objects.create(
        workspace=workspace, meter="ai.agent_chat", idempotency_key="usage-chat-0001",
        units=Decimal("2"), points=Decimal("1.2000"), period_start=september, price=price,
        recorded_at=timezone.make_aware(datetime(2026, 9, 7, 10, 0)),
    )
    WorkspaceMeterUsage.objects.create(
        workspace=workspace, meter="ai.agent_chat", idempotency_key="usage-chat-0002",
        units=Decimal("3"), points=Decimal("1.8000"), period_start=september, price=price,
        recorded_at=timezone.make_aware(datetime(2026, 9, 8, 10, 0)),
    )
    WorkspaceMeterUsage.objects.create(
        workspace=workspace, meter="store.image", idempotency_key="usage-image-001",
        units=Decimal("1"), points=Decimal("0.5000"), period_start=september, price=image_price,
        recorded_at=timezone.make_aware(datetime(2026, 9, 8, 11, 0)),
    )
    WorkspaceMeterUsage.objects.create(
        workspace=workspace, meter="ai.agent_chat", idempotency_key="usage-august-01",
        units=Decimal("100"), points=Decimal("100.0000"), period_start=date(2026, 8, 1), price=price,
    )

    client = APIClient()
    client.force_authenticate(user=tenant_admin)
    denied = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/usage/?month=2026-09")
    assert denied.status_code == 403

    client.force_authenticate(user=superuser)
    response = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/usage/?month=2026-09")

    assert response.status_code == 200
    assert response.data["month"] == "2026-09"
    assert response.data["currency"] == get_default_currency_for_workspace(workspace)
    assert response.data["cap_points"] == "10.0000"
    assert response.data["used_points"] == "3.5000"
    assert response.data["remaining_points"] == "6.5000"
    assert response.data["estimated_amount"] is None
    assert response.data["overdue"] is False
    assert response.data["meters"] == [
        {"meter": "ai.agent_chat", "quantity": "5", "points": "3.0000", "amount": None},
        {"meter": "store.image", "quantity": "1", "points": "0.5000", "amount": None},
    ]
    assert response.data["days"] == [
        {
            "day": "2026-09-08", "points": "2.3000",
            "meters": [
                {"meter": "ai.agent_chat", "quantity": "3", "points": "1.8000"},
                {"meter": "store.image", "quantity": "1", "points": "0.5000"},
            ],
        },
        {
            "day": "2026-09-07", "points": "1.2000",
            "meters": [{"meter": "ai.agent_chat", "quantity": "2", "points": "1.2000"}],
        },
    ]

    detail = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/")
    assert detail.status_code == 200
    assert detail.data["capabilities"] == {"extension_management": False, "usage": True}


@pytest.mark.django_db
def test_workspace_usage_rejects_invalid_reporting_month():
    superuser = User.objects.create_superuser(
        username="usage-month-root", password="secret", email="usage-month@example.test",
    )
    workspace = Workspace.objects.create(name="Month Workspace", slug="month-workspace", is_active=True)
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/usage/?month=September")

    assert response.status_code == 400
    assert response.data["month"] == "Use a reporting month in YYYY-MM format."


@pytest.mark.django_db
def test_superuser_can_set_and_correct_platform_exchange_rate():
    superuser = User.objects.create_superuser(
        username="rate-root", password="secret", email="rates@example.test",
    )
    Currency.objects.create(code="NZD", name="New Zealand Dollar", symbol="$", is_active=True)
    Currency.objects.create(code="USD", name="US Dollar", symbol="US$", is_active=True)
    client = APIClient()
    client.force_authenticate(user=superuser)

    created = client.post("/api/v1/platform/console/exchange-rates/", {
        "from": "NZD", "to": "USD", "rate": "0.600000", "effective_date": "2026-09-19", "confirm": True,
    }, format="json")
    assert created.status_code == 201
    assert created.data["source"] == "manual"
    assert created.data["entered_by"]["id"] == superuser.id

    corrected = client.post("/api/v1/platform/console/exchange-rates/", {
        "from": "NZD", "to": "USD", "rate": "0.610000", "effective_date": "2026-09-19", "confirm": True,
    }, format="json")
    assert corrected.status_code == 200
    assert ExchangeRate.objects.filter(from_currency__code="NZD", to_currency__code="USD").count() == 1
    assert corrected.data["rate"] == "0.610000"
    assert PlatformAuditEvent.objects.filter(action="configuration.exchange_rate_set").count() == 2


@pytest.mark.django_db
def test_superuser_can_set_workspace_usage_cap_and_grant_once():
    superuser = User.objects.create_superuser(
        username="cap-root", password="secret", email="cap@example.test",
    )
    workspace = Workspace.objects.create(name="Cap Workspace", slug="cap-workspace", is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    client = APIClient()
    client.force_authenticate(user=superuser)

    inherited = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/usage-cap/")
    assert inherited.status_code == 200
    assert inherited.data["source"] == "platform"

    own = client.patch(
        f"/api/v1/platform/console/workspaces/{workspace.id}/usage-cap/", {"cap_points": "0", "confirm": True}, format="json",
    )
    assert own.status_code == 200
    assert own.data["source"] == "workspace"
    assert own.data["effective_cap_points"] == "0.0000"

    restored = client.patch(
        f"/api/v1/platform/console/workspaces/{workspace.id}/usage-cap/", {"cap_points": None, "confirm": True}, format="json",
    )
    assert restored.status_code == 200
    assert restored.data["source"] == "platform"

    grant = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/grants/",
        {"key": "batch_management", "months": 12, "reason": "Migration support", "confirm": True}, format="json",
    )
    assert grant.status_code == 201
    assert grant.data["entitlement"]["key"] == "batch_management"
    assert grant.data["entitlement"]["is_effective"] is True
    duplicate = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/grants/",
        {"key": "batch_management", "months": 12, "reason": "Duplicate", "confirm": True}, format="json",
    )
    assert duplicate.status_code == 409
    assert duplicate.data["code"] == "already_entitled"


@pytest.mark.django_db
def test_runtime_entitlement_enables_batch_management_and_can_be_revoked(settings):
    settings.BFG2_SETTINGS = {
        **getattr(settings, "BFG2_SETTINGS", {}),
        "ENABLE_BATCH_MANAGEMENT": False,
    }
    superuser = User.objects.create_superuser(
        username="grant-root", password="secret", email="grant@example.test",
    )
    workspace = Workspace.objects.create(name="Granted Feature", slug="granted-feature", is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    client = APIClient()
    client.force_authenticate(user=superuser)

    assert is_batch_management_enabled(workspace) is False
    unknown = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/grants/",
        {"key": "resale.pro", "months": 1, "reason": "Unsupported feature", "confirm": True}, format="json",
    )
    assert unknown.status_code == 400
    assert unknown.data["code"] == "unknown_entitlement_feature"

    granted = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/grants/",
        {"key": "batch_management", "never_expires": True, "reason": "Plan migration", "confirm": True}, format="json",
    )
    assert granted.status_code == 201
    grant_id = granted.data["entitlement"]["id"]
    assert is_batch_management_enabled(workspace) is True

    listed = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/grants/")
    assert listed.status_code == 200
    assert listed.data == [granted.data["entitlement"]]

    revoked = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/grants/{grant_id}/revoke/",
        {"reason": "Plan migration rolled back", "confirm": True}, format="json",
    )
    assert revoked.status_code == 200
    assert revoked.data["entitlement"]["status"] == "revoked"
    assert revoked.data["entitlement"]["is_effective"] is False
    assert is_batch_management_enabled(workspace) is False
    assert PlatformAuditEvent.objects.filter(action="workspace.entitlement_revoked").count() == 1

    repeated = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/grants/{grant_id}/revoke/",
        {"reason": "Repeated revoke", "confirm": True}, format="json",
    )
    assert repeated.status_code == 200
    assert PlatformAuditEvent.objects.filter(action="workspace.entitlement_revoked").count() == 1


@pytest.mark.django_db
def test_platform_superuser_can_read_workspace_operations_without_worker_error_text():
    superuser = User.objects.create_superuser(
        username="operations-root", password="secret", email="operations@example.test",
    )
    workspace = Workspace.objects.create(name="Operations Workspace", slug="operations-workspace", is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    failed = WorkspaceOperation.objects.create(
        workspace=workspace, operation="migrate", status="failed", initiated_by=superuser,
        details={"target_cluster": "uat-apac", "redis_url": "rediss://private.example.test/0"},
        error_message="Could not reach redis://private.example.test/0 with secret=sensitive",
        started_at=timezone.now() - timedelta(minutes=1),
    )
    completed = WorkspaceOperation.objects.create(
        workspace=workspace, operation="suspend", status="completed", initiated_by=superuser,
        details={"reason": "Maintenance window"},
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/operations/?limit=1")

    assert response.status_code == 200
    assert response.data[0]["id"] == str(completed.id)
    assert response.data[0]["error"] is None
    all_operations = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/operations/?limit=2")
    assert all_operations.status_code == 200
    failed_item = next(item for item in all_operations.data if item["id"] == str(failed.id))
    assert failed_item["details"]["redis_url"] == "[redacted]"
    assert failed_item["error"] == "Operation failed. Inspect secured server logs."
    assert "secret" not in str(failed_item)


@pytest.mark.django_db
def test_platform_workspace_operations_refuse_non_superusers():
    superuser = User.objects.create_superuser(
        username="operations-owner", password="secret", email="operations-owner@example.test",
    )
    workspace = _embedded_workspace_member(superuser, slug="operations-private")
    tenant_admin = User.objects.create_user(username="operations-tenant", password="secret", is_staff=True)
    client = APIClient()
    client.force_authenticate(user=tenant_admin)

    response = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/operations/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_cluster_inventory_never_returns_redis_connection_value():
    Cluster.objects.create(
        id="private-cluster",
        name="Private Cluster",
        region="apac",
        api_base_url="https://api.example.test",
        frontend_base_url="https://shop.example.test",
        db_host="db.example.test",
        redis_url="rediss://secret@example.test:6379/0",
        s3_bucket="private-cluster",
    )
    superuser = User.objects.create_superuser(
        username="cluster-root", password="secret", email="cluster-root@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.get("/api/v1/platform/console/clusters/")

    assert response.status_code == 200
    assert response.data[0]["redis_configured"] is True
    assert "redis_url" not in response.data[0]


def _embedded_workspace_member(user, *, slug="owned-workspace", role_code="admin"):
    workspace = Workspace.objects.create(
        name=slug.replace("-", " ").title(), slug=slug, is_active=True,
    )
    WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    role = StaffRole.objects.create(
        workspace=workspace,
        name=role_code.title(),
        code=role_code,
        is_system=True,
    )
    StaffMember.all_objects.create(
        workspace=workspace, user=user, role=role, is_active=True,
    )
    return workspace


@pytest.mark.django_db
def test_owner_workspace_detail_remains_available_outside_platform_console(settings):
    settings.PLATFORM_EMBEDDED = True
    owner = User.objects.create_user(
        username="workspace-owner", password="secret", email="owner@example.test",
    )
    workspace = _embedded_workspace_member(owner)
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.get(f"/api/v1/platform/workspaces/{workspace.id}/")

    assert response.status_code == 200
    assert response.data["owned_by_viewer"] is True
    assert response.data["owner"]["id"] == owner.id
    assert response.data["extensions"] == []
    assert response.data["active_extensions"] == []
    assert response.data["capabilities"] == {
        "extension_management": False,
        "usage": False,
    }


@pytest.mark.django_db
def test_workspace_detail_is_hidden_from_unrelated_authenticated_user(settings):
    settings.PLATFORM_EMBEDDED = True
    owner = User.objects.create_user(username="detail-owner", password="secret")
    outsider = User.objects.create_user(username="detail-outsider", password="secret")
    workspace = _embedded_workspace_member(owner, slug="private-workspace")
    client = APIClient()
    client.force_authenticate(user=outsider)

    response = client.get(f"/api/v1/platform/workspaces/{workspace.id}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_standalone_owner_workspace_detail_uses_platform_membership(settings):
    settings.PLATFORM_EMBEDDED = False
    owner = User.objects.create_user(
        username="standalone-owner", password="secret", email="standalone@example.test",
    )
    workspace = Workspace.objects.create(
        name="Standalone Workspace", slug="standalone-workspace", is_active=True,
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    PlatformMembership.objects.create(
        user=owner, profile=profile, role="owner", is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.get(f"/api/v1/platform/workspaces/{workspace.id}/")

    assert response.status_code == 200
    assert response.data["owner"]["id"] == owner.id
    assert response.data["owned_by_viewer"] is True
    assert response.data["staff_count"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["suspend", "resume"])
def test_tenant_member_cannot_use_legacy_platform_lifecycle_actions(settings, action):
    settings.PLATFORM_EMBEDDED = True
    member = User.objects.create_user(username=f"member-{action}", password="secret")
    workspace = _embedded_workspace_member(member, slug=f"workspace-{action}")
    client = APIClient()
    client.force_authenticate(user=member)

    response = client.post(f"/api/v1/platform/workspaces/{workspace.id}/{action}/", {})

    assert response.status_code == 403


@pytest.mark.django_db
def test_superuser_can_use_legacy_platform_lifecycle_action_when_member(settings):
    settings.PLATFORM_EMBEDDED = True
    superuser = User.objects.create_superuser(
        username="lifecycle-root", password="secret", email="root@example.test",
    )
    workspace = _embedded_workspace_member(superuser, slug="root-workspace")
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.post(
        f"/api/v1/platform/workspaces/{workspace.id}/suspend/",
        {"confirm": True, "reason": "Incident investigation"},
        format="json",
    )

    assert response.status_code == 200
    workspace.refresh_from_db()
    assert workspace.is_active is False
    event = PlatformAuditEvent.objects.get(action="workspace.suspend", target_id=str(workspace.id))
    assert event.actor_id == superuser.id
    assert event.reason == "Incident investigation"


@pytest.mark.django_db
def test_cluster_write_requires_confirmation_and_records_redacted_audit_event():
    superuser = User.objects.create_superuser(
        username="cluster-change-root", password="secret", email="root@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)
    payload = {
        "id": "audit-cluster",
        "name": "Audit Cluster",
        "region": "apac",
        "api_base_url": "https://api.example.test",
        "db_host": "db.example.test",
        "redis_url": "rediss://private@example.test:6379/0",
        "s3_bucket": "audit-cluster",
    }

    refused = client.post("/api/v1/platform/console/clusters/", payload, format="json")
    response = client.post(
        "/api/v1/platform/console/clusters/",
        {**payload, "confirm": True, "reason": "Create UAT infrastructure"},
        format="json",
    )

    assert refused.status_code == 400
    assert response.status_code == 201
    assert "redis_url" not in response.data
    event = PlatformAuditEvent.objects.get(action="cluster.created", target_id="audit-cluster")
    assert event.reason == "Create UAT infrastructure"
    assert event.after["redis_configured"] is True
    assert "redis_url" not in event.after


@pytest.mark.django_db
def test_cluster_update_uses_configuration_version_and_stops_allocation_when_inactive():
    superuser = User.objects.create_superuser(
        username="cluster-version-root", password="secret", email="root@example.test",
    )
    cluster = Cluster.objects.create(
        id="versioned-cluster", name="Versioned", region="apac",
        api_base_url="https://api.example.test", db_host="db.example.test",
        redis_url="rediss://private.example.test/0", s3_bucket="versioned",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    changed = client.patch(
        f"/api/v1/platform/console/clusters/{cluster.id}/",
        {"is_active": False, "expected_version": 1, "confirm": True, "reason": "Maintenance window"},
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["config_version"] == 2
    assert changed.data["is_accepting_new"] is False

    stale = client.patch(
        f"/api/v1/platform/console/clusters/{cluster.id}/",
        {"name": "Stale write", "expected_version": 1, "confirm": True, "reason": "Outdated browser tab"},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.data["code"] == "cluster_version_conflict"


@pytest.mark.django_db
def test_workspace_service_assigns_only_an_eligible_cluster_and_enforces_capacity():
    user = User.objects.create_user(username="capacity-owner", password="secret")
    cluster = Cluster.objects.create(
        id="capacity-cluster", name="Capacity", region="apac",
        api_base_url="https://api.example.test", frontend_base_url="https://shops.example.test",
        db_host="db.example.test", redis_url="rediss://private.example.test/0", s3_bucket="capacity",
        max_workspaces=1,
    )
    service = WorkspaceService(workspace=None, user=user)

    first = service.create_workspace(name="Capacity One", slug="capacity-one", owner_user=user, region="apac")
    first_profile = WorkspacePlatformProfile.objects.get(workspace=first)
    cluster.refresh_from_db()
    assert first_profile.cluster_id == cluster.id
    assert cluster.current_workspaces == 1

    with pytest.raises(WorkspaceCapacityUnavailable):
        service.create_workspace(name="Capacity Two", slug="capacity-two", owner_user=user, region="apac")


@pytest.mark.django_db
def test_workspace_create_returns_a_safe_capacity_error_instead_of_a_server_error():
    user = User.objects.create_user(username="capacity-api-owner", password="secret")
    Cluster.objects.create(
        id="stopped-cluster", name="Stopped", region="apac",
        api_base_url="https://api.example.test", db_host="db.example.test",
        redis_url="rediss://private.example.test/0", s3_bucket="stopped",
        is_active=False, is_accepting_new=False,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post("/api/v1/platform/workspaces/", {
        "name": "Blocked workspace", "slug": "blocked-workspace", "region": "apac",
    }, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "workspace_capacity_unavailable"


@pytest.mark.django_db
def test_workspace_service_does_not_assign_a_cluster_with_a_known_bad_health_state():
    user = User.objects.create_user(username="unhealthy-cluster-owner", password="secret")
    Cluster.objects.create(
        id="unhealthy-cluster", name="Unhealthy", region="apac",
        api_base_url="https://api.example.test", db_host="db.example.test",
        redis_url="rediss://private.example.test/0", s3_bucket="unhealthy",
        health_status="degraded", max_workspaces=20,
    )
    service = WorkspaceService(workspace=None, user=user)

    with pytest.raises(WorkspaceCapacityUnavailable):
        service.create_workspace(
            name="Blocked by health", slug="blocked-by-health", owner_user=user, region="apac",
        )


@pytest.mark.django_db
def test_workspace_deletion_schedule_is_idempotent_and_can_be_explicitly_cancelled(settings):
    settings.PLATFORM_EMBEDDED = True
    superuser = User.objects.create_superuser(
        username="lifecycle-root", password="secret", email="lifecycle@example.test",
    )
    workspace = _embedded_workspace_member(superuser, slug="recoverable-workspace")
    client = APIClient()
    client.force_authenticate(user=superuser)

    deleted = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/delete/",
        {"confirm": True, "reason": "Requested closure"}, format="json",
    )
    assert deleted.status_code == 200
    scheduled_at = deleted.data["scheduled_deletion_at"]
    assert scheduled_at
    assert deleted.data["is_active"] is False

    repeated = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/delete/",
        {"confirm": True, "reason": "Duplicate request"}, format="json",
    )
    assert repeated.status_code == 200
    assert repeated.data["scheduled_deletion_at"] == scheduled_at
    assert PlatformAuditEvent.objects.filter(action="workspace.deletion_scheduled").count() == 1

    restored = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/restore/",
        {"confirm": True, "reason": "Keep the workspace"}, format="json",
    )
    assert restored.status_code == 200
    assert restored.data["is_active"] is True
    assert restored.data["scheduled_deletion_at"] is None
    assert PlatformAuditEvent.objects.filter(action="workspace.deletion_cancelled").exists()


@pytest.mark.django_db
def test_workspace_configuration_export_import_maps_owner_cluster_and_pending_domains(settings):
    settings.PLATFORM_EMBEDDED = True
    superuser = User.objects.create_superuser(
        username="export-root", password="secret", email="root@example.test",
    )
    owner = User.objects.create_user(username="export-owner", password="secret", email="owner@example.test")
    cluster = Cluster.objects.create(
        id="import-cluster", name="Import", region="apac",
        api_base_url="https://api.example.test", frontend_base_url="https://shops.example.test",
        db_host="db.example.test", redis_url="rediss://private.example.test/0", s3_bucket="import",
    )
    workspace = _embedded_workspace_member(owner, slug="export-source")
    profile = WorkspacePlatformProfile.objects.get(workspace=workspace)
    profile.cluster = cluster
    profile.save(update_fields=["cluster", "updated_at"])
    WorkspaceDomain.objects.create(
        workspace=workspace, hostname="source.example.test", kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED, ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    unconfirmed = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/export/",
        {"reason": "Move configuration template"}, format="json",
    )
    assert unconfirmed.status_code == 400
    assert PlatformAuditEvent.objects.filter(action="workspace.exported").count() == 0

    exported = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/export/",
        {"confirm": True, "reason": "Move configuration template"}, format="json",
    )
    assert exported.status_code == 200
    import json
    payload = json.loads(exported.content)
    assert payload["scope"] == "configuration-template"
    assert payload["owner_email"] == owner.email
    payload["workspace"]["name"] = "Imported Workspace"
    payload["workspace"]["slug"] = "imported-workspace"
    payload["custom_domains"] = [{"hostname": "imported.example.test"}]
    payload.update({"confirm": True, "reason": "Move configuration template"})

    imported = client.post("/api/v1/platform/console/workspaces/import-workspace/", payload, format="json")
    assert imported.status_code == 201
    restored = Workspace.objects.get(slug="imported-workspace")
    restored_profile = WorkspacePlatformProfile.objects.get(workspace=restored)
    assert restored_profile.cluster_id == cluster.id
    assert StaffMember.all_objects.filter(workspace=restored, user=owner, is_active=True).exists()
    restored_domain = WorkspaceDomain.objects.get(workspace=restored, hostname="imported.example.test")
    assert restored_domain.verification_status == WorkspaceDomain.VERIFICATION_PENDING
    assert restored_domain.is_primary is False


@pytest.mark.django_db
def test_workspace_import_requires_an_active_owner_and_supported_format():
    superuser = User.objects.create_superuser(
        username="import-root", password="secret", email="root@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    missing_owner = client.post("/api/v1/platform/console/workspaces/import-workspace/", {
        "format": "idlevo-workspace-v1", "workspace": {"name": "No owner", "slug": "no-owner"},
        "confirm": True, "reason": "Test import",
    }, format="json")
    assert missing_owner.status_code == 400
    assert missing_owner.data["code"] == "workspace_import_owner_required"

    unsupported = client.post("/api/v1/platform/console/workspaces/import-workspace/", {
        "format": "other-export-v1", "workspace": {"name": "Wrong", "slug": "wrong"},
        "confirm": True, "reason": "Test import",
    }, format="json")
    assert unsupported.status_code == 400
    assert unsupported.data["code"] == "unsupported_workspace_import_format"


@pytest.mark.django_db
def test_workspace_import_does_not_expose_cluster_capacity_failure_details():
    superuser = User.objects.create_superuser(
        username="import-capacity-root", password="secret", email="root-capacity@example.test",
    )
    owner = User.objects.create_user(
        username="import-capacity-owner", password="secret", email="owner-capacity@example.test",
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    with patch(
        "bfg.platform.views.console_views.WorkspaceService.create_workspace",
        side_effect=WorkspaceCapacityUnavailable("The internal Cluster allocator is unavailable."),
    ):
        response = client.post("/api/v1/platform/console/workspaces/import-workspace/", {
            "format": "idlevo-workspace-v1",
            "workspace": {"name": "Capacity import", "slug": "capacity-import"},
            "owner_email": owner.email,
            "confirm": True,
            "reason": "Capacity import regression",
        }, format="json")

    assert response.status_code == 409
    assert response.data == {
        "detail": "No Cluster has capacity for this workspace",
        "code": "workspace_capacity_unavailable",
    }
    assert "internal Cluster allocator" not in response.data["detail"]


@pytest.mark.django_db
@patch("bfg.platform.views.console_views.UserService.request_password_reset", return_value=True)
def test_password_reset_uses_standalone_platform_owner_and_only_that_owner(mock_reset, settings):
    settings.PLATFORM_EMBEDDED = False
    superuser = User.objects.create_superuser(
        username="password-root", password="secret", email="root@example.test",
    )
    owner = User.objects.create_user(username="standalone-password-owner", password="secret", email="owner@example.test")
    outsider = User.objects.create_user(username="reset-outsider", password="secret", email="outsider@example.test")
    cluster = Cluster.objects.create(
        id="password-cluster", name="Password", region="apac",
        api_base_url="https://api.example.test", frontend_base_url="https://console.example.test",
        db_host="db.example.test", redis_url="rediss://private.example.test/0", s3_bucket="password",
    )
    workspace = Workspace.objects.create(name="Password Workspace", slug="password-workspace", is_active=True)
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=owner, profile=profile, role="owner", is_active=True)
    client = APIClient()
    client.force_authenticate(user=superuser)

    reset = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/reset-admin-password/",
        {"confirm": True, "reason": "Support request"}, format="json",
    )
    assert reset.status_code == 200
    mock_reset.assert_called_once_with(owner.email, "https://console.example.test")

    refused = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/reset-admin-password/",
        {"confirm": True, "reason": "Wrong recipient", "email": outsider.email}, format="json",
    )
    assert refused.status_code == 400
    assert mock_reset.call_count == 1


@pytest.mark.django_db
@patch("bfg.platform.views.console_views.UserService.request_password_reset", return_value=False)
def test_password_reset_reports_delivery_failure_without_audit_event(mock_reset, settings):
    settings.PLATFORM_EMBEDDED = True
    settings.FRONTEND_URL = "https://uat.idlevo.com"
    superuser = User.objects.create_superuser(
        username="mail-root", password="secret", email="root@example.test",
    )
    workspace = _embedded_workspace_member(superuser, slug="mail-workspace")
    client = APIClient()
    client.force_authenticate(user=superuser)

    response = client.post(
        f"/api/v1/platform/console/workspaces/{workspace.id}/reset-admin-password/",
        {"confirm": True, "reason": "Support request"}, format="json",
    )
    assert response.status_code == 503
    assert not PlatformAuditEvent.objects.filter(action="workspace.password_reset_requested").exists()


@pytest.mark.django_db
def test_audit_events_are_paginated_filterable_and_redacted_for_superusers():
    superuser = User.objects.create_superuser(
        username="audit-reader", password="secret", email="reader@example.test",
    )
    older = PlatformAuditEvent.objects.create(
        action="workspace.suspend",
        target_type="workspace",
        target_id="23",
        reason="Investigate an incident",
        actor=superuser,
        after={"redis_url": "rediss://do-not-return", "nested": {"api_key": "private"}},
    )
    newer = PlatformAuditEvent.objects.create(
        action="cluster.updated",
        target_type="cluster",
        target_id="uat-apac",
        reason="Pause new allocations",
        actor=superuser,
    )
    client = APIClient()
    client.force_authenticate(user=superuser)

    first = client.get("/api/v1/platform/console/audit-events/?limit=1")

    assert first.status_code == 200
    assert first.data["results"][0]["id"] == str(newer.id)
    assert first.data["next"]
    assert "source_ip" not in first.data["results"][0]
    second = client.get(f"/api/v1/platform/console/audit-events/?cursor={first.data['next']}")
    assert second.status_code == 200
    assert second.data["results"][0]["id"] == str(older.id)
    assert second.data["results"][0]["after"]["redis_url"] == "[redacted]"
    assert second.data["results"][0]["after"]["nested"]["api_key"] == "[redacted]"

    filtered = client.get("/api/v1/platform/console/audit-events/?target_type=workspace&target_id=23")
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.data["results"]] == [str(older.id)]


@pytest.mark.django_db
def test_workspace_patch_cannot_rebind_another_workspace_domain(settings):
    settings.PLATFORM_EMBEDDED = True
    first_owner = User.objects.create_user(username="first-owner", password="secret")
    second_owner = User.objects.create_user(username="second-owner", password="secret")
    first = _embedded_workspace_member(first_owner, slug="first-domain-owner")
    second = _embedded_workspace_member(second_owner, slug="second-domain-owner")
    domain = WorkspaceDomain.objects.create(
        workspace=first,
        hostname="claimed.example.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )
    client = APIClient()
    client.force_authenticate(user=second_owner)

    response = client.patch(
        f"/api/v1/platform/workspaces/{second.id}/",
        {"domain": "https://claimed.example.test/path"},
        format="json",
    )

    assert response.status_code == 400
    domain.refresh_from_db()
    assert domain.workspace_id == first.id


@pytest.mark.django_db
def test_workspace_patch_adds_new_custom_domain_as_pending_without_displacing_verified_domain(settings):
    settings.PLATFORM_EMBEDDED = True
    owner = User.objects.create_user(username="pending-domain-owner", password="secret")
    workspace = _embedded_workspace_member(owner, slug="pending-domain-owner")
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="verified.example.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.patch(
        f"/api/v1/platform/workspaces/{workspace.id}/",
        {"domain": "candidate.example.test"},
        format="json",
    )

    assert response.status_code == 200
    current = WorkspaceDomain.objects.get(hostname="verified.example.test")
    candidate = WorkspaceDomain.objects.get(hostname="candidate.example.test")
    assert current.is_primary is True
    assert candidate.verification_status == WorkspaceDomain.VERIFICATION_PENDING
    assert candidate.is_primary is False


@pytest.mark.django_db
def test_workspace_create_serializer_cannot_claim_existing_domain():
    workspace = Workspace.objects.create(
        name="Existing Domain", slug="existing-domain", is_active=True,
    )
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="existing.example.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    serializer = WorkspaceCreateSerializer(data={
        "name": "New Workspace",
        "slug": "new-workspace",
        "domain": "EXISTING.example.test",
        "region": "apac",
    })

    assert serializer.is_valid() is False
    assert "domain" in serializer.errors

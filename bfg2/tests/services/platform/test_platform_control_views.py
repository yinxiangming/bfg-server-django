from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.models import Workspace
from bfg.finance.models import Currency
from bfg.platform.models import (
    Cluster,
    ClusterHealthObservation,
    PlatformAuditEvent,
    WorkspacePlacementRequest,
)
from bfg.platform.models.workspace_profile import WorkspacePlatformProfile
from bfg.platform.services.cluster_health import (
    ClusterHealthProbeConfigurationError,
    ClusterHealthProbeResult,
    cluster_health_url,
)
from bfg.platform.services.placement_queue import expire_due_reservations


pytestmark = pytest.mark.django_db

CONTROL = "/api/v1/platform/control/"
User = get_user_model()


def client_for(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def test_control_plane_requires_a_django_superuser():
    Workspace.objects.create(name="Shop", slug="shop", is_active=True)
    regular = User.objects.create_user(username="regular", password="secret")
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    assert client_for().get(f"{CONTROL}workspaces/").status_code in (401, 403)
    refused = client_for(regular).get(f"{CONTROL}workspaces/")
    assert refused.status_code == 403
    assert refused.data["code"] == "platform_superuser_required"
    allowed = client_for(superuser).get(f"{CONTROL}workspaces/")
    assert allowed.status_code == 200
    assert allowed.data["count"] == 1
    assert client_for(regular).get(f"{CONTROL}placement-requests/").status_code == 403


def test_control_status_is_a_superuser_only_capability_document():
    regular = User.objects.create_user(username="regular", password="secret")
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    assert client_for(regular).get(f"{CONTROL}status/").status_code == 403
    response = client_for(superuser).get(f"{CONTROL}status/")
    assert response.status_code == 200
    assert response.data == {
        "is_platform_superuser": True,
        "platform_capabilities": {
            "cluster_management": True,
            "audit_log": True,
            "configuration": True,
            "exchange_rates": True,
        },
    }


@pytest.mark.parametrize(
    "path",
    (
        "variables/",
        "meter-prices/",
        "exchange-rates/",
        "workspaces/1/usage-cap/",
        "workspaces/1/grants/",
    ),
)
def test_historical_privileged_console_routes_are_not_exposed(path):
    """Only the audited control-plane contract may manage deployment settings."""
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    response = client_for(superuser).get(f"/api/v1/platform/console/{path}")

    assert response.status_code == 404


def test_suspend_is_confirmed_idempotent_and_audited():
    workspace = Workspace.objects.create(name="Shop", slug="shop", is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=workspace)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)
    url = f"{CONTROL}workspaces/{workspace.id}/suspend/"

    assert client.post(url, {"reason": "Suspected payment fraud"}, format="json").status_code == 400
    response = client.post(
        url,
        {"confirm": True, "reason": "Suspected payment fraud"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="action-key-0001",
    )
    assert response.status_code == 200
    workspace.refresh_from_db()
    assert workspace.is_active is False
    assert PlatformAuditEvent.objects.filter(action="workspace.suspend", target_id=str(workspace.id)).exists()

    replay = client.post(
        url,
        {"confirm": True, "reason": "Suspected payment fraud"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="action-key-0001",
    )
    assert replay.status_code == 200
    assert replay["Idempotent-Replayed"] == "true"
    assert PlatformAuditEvent.objects.filter(action="workspace.suspend", target_id=str(workspace.id)).count() == 1


def test_resume_handles_a_workspace_without_a_platform_profile():
    workspace = Workspace.objects.create(name="Legacy Shop", slug="legacy-shop", is_active=False)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    response = client_for(superuser).post(
        f"{CONTROL}workspaces/{workspace.id}/resume/",
        {"confirm": True, "reason": "Correct accidental deactivation"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="resume-key-0001",
    )

    assert response.status_code == 200
    workspace.refresh_from_db()
    assert workspace.is_active is True


def test_restore_clears_the_scheduled_deletion_deadline():
    workspace = Workspace.objects.create(name="Recoverable Shop", slug="recoverable-shop", is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=workspace)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)
    delete = client.post(
        f"{CONTROL}workspaces/{workspace.id}/delete/",
        {"confirm": True, "reason": "Customer requested closure"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="delete-key-0001",
    )
    assert delete.status_code == 200
    workspace.platform_profile.refresh_from_db()
    assert workspace.platform_profile.scheduled_deletion_at is not None

    restore = client.post(
        f"{CONTROL}workspaces/{workspace.id}/restore/",
        {"confirm": True, "reason": "Customer cancelled closure"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="restore-key-0001",
    )
    assert restore.status_code == 200
    workspace.refresh_from_db()
    workspace.platform_profile.refresh_from_db()
    assert workspace.is_active is True
    assert workspace.platform_profile.scheduled_deletion_at is None


def test_cluster_create_keeps_redis_secret_out_of_response_and_audit():
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    response = client_for(superuser).post(
        f"{CONTROL}clusters/",
        {
            "confirm": True,
            "reason": "Add the UAT cluster",
            "id": "uat",
            "name": "UAT",
            "region": "apac",
            "api_base_url": "https://api-uat.example.test",
            "frontend_base_url": "https://uat.example.test",
            "db_host": "db.example.test",
            "db_port": 3306,
            "redis_url": "rediss://platform-secret@example.test:6379/0",
            "s3_bucket": "uat-workspaces",
            "max_workspaces": 50,
            "is_accepting_new": True,
            "is_active": True,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="cluster-key-0001",
    )

    assert response.status_code == 201
    assert response.data["redis_configured"] is True
    assert "redis_url" not in response.data
    cluster = Cluster.objects.get(pk="uat")
    assert cluster.config_version == 1
    event = PlatformAuditEvent.objects.get(action="cluster.created")
    assert event.after["redis_configured"] is True
    assert "redis_url" not in event.after


def test_cluster_health_check_is_registered_on_the_cluster_route(monkeypatch):
    cluster = Cluster.objects.create(
        id="uat",
        name="UAT",
        region="apac",
        api_base_url="https://api-uat.example.test",
        db_host="db.example.test",
        redis_url="rediss://platform-secret@example.test:6379/0",
        s3_bucket="uat-workspaces",
    )
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    monkeypatch.setattr(
        "bfg.platform.views.control_views.probe_cluster_health",
        lambda _cluster: ClusterHealthProbeResult(health_status="healthy", http_status=200),
    )

    response = client_for(superuser).post(
        f"{CONTROL}clusters/{cluster.id}/health-check/",
        {"confirm": True, "reason": "Verify the UAT deployment health"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="health-key-0001",
    )

    assert response.status_code == 200
    assert response.data["health_status"] == "healthy"
    cluster.refresh_from_db()
    assert cluster.health_status == "healthy"
    assert PlatformAuditEvent.objects.filter(action="cluster.health_checked", target_id=cluster.id).exists()
    observation = ClusterHealthObservation.objects.get(cluster=cluster)
    assert observation.health_status == "healthy"
    assert observation.http_status == 200
    history = client_for(superuser).get(f"{CONTROL}clusters/{cluster.id}/health-observations/?limit=5")
    assert history.status_code == 200
    assert history.data[0]["outcome"] == "checked"


def test_cluster_health_summary_is_superuser_only_and_marks_stale_observations():
    healthy = Cluster.objects.create(
        id="healthy", name="Healthy", region="apac", api_base_url="https://healthy.example.test",
        db_host="db.example.test", redis_url="rediss://redis.example.test", s3_bucket="healthy",
    )
    stale = Cluster.objects.create(
        id="stale", name="Stale", region="apac", api_base_url="https://stale.example.test",
        db_host="db.example.test", redis_url="rediss://redis.example.test", s3_bucket="stale",
    )
    malformed = Cluster.objects.create(
        id="malformed", name="Malformed", region="apac", api_base_url="https://malformed.example.test",
        db_host="db.example.test", redis_url="rediss://redis.example.test", s3_bucket="malformed",
    )
    inactive = Cluster.objects.create(
        id="inactive", name="Inactive", region="apac", api_base_url="https://inactive.example.test",
        db_host="db.example.test", redis_url="rediss://redis.example.test", s3_bucket="inactive",
        is_active=False, is_accepting_new=False,
    )
    observed_at = timezone.now()
    ClusterHealthObservation.objects.create(
        cluster=healthy, health_status="healthy", http_status=200, observed_at=observed_at,
    )
    ClusterHealthObservation.objects.create(
        cluster=stale, health_status="down", observed_at=observed_at - timedelta(hours=25),
    )
    ClusterHealthObservation.objects.create(
        cluster=malformed, health_status="unexpected", observed_at=observed_at,
    )
    ClusterHealthObservation.objects.create(
        cluster=inactive, health_status="down", observed_at=observed_at,
    )
    regular = User.objects.create_user(username="regular", password="secret")
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    assert client_for(regular).get(f"{CONTROL}clusters/health-summary/").status_code == 403
    response = client_for(superuser).get(f"{CONTROL}clusters/health-summary/")

    assert response.status_code == 200
    assert response.data["window_hours"] == 24
    assert response.data["summary"] == {
        "active_clusters": 3,
        "inactive_clusters": 1,
        "checked_within_window": 2,
        "stale_or_unchecked": 1,
        "healthy": 1,
        "degraded": 0,
        "down": 0,
        "unknown": 2,
    }
    rows = {row["id"]: row for row in response.data["clusters"]}
    assert rows["healthy"]["is_stale_or_unchecked"] is False
    assert rows["healthy"]["last_observation"]["http_status"] == 200
    assert rows["stale"]["is_stale_or_unchecked"] is True
    assert rows["stale"]["last_observation"]["health_status"] == "down"
    assert rows["malformed"]["is_stale_or_unchecked"] is False
    assert "api_base_url" not in rows["healthy"]
    assert "redis_url" not in rows["healthy"]


def test_cluster_health_configuration_refusal_is_observed_and_audited(settings):
    settings.CLUSTER_HEALTH_ALLOWED_HOSTS = []
    cluster = Cluster.objects.create(
        id="unavailable",
        name="Unavailable",
        region="apac",
        api_base_url="https://api-uat.example.test",
        db_host="db.example.test",
        redis_url="rediss://platform-secret@example.test:6379/0",
        s3_bucket="uat-workspaces",
    )
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    response = client_for(superuser).post(
        f"{CONTROL}clusters/{cluster.id}/health-check/",
        {"confirm": True, "reason": "The health allowlist has not been configured"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="health-key-0002",
    )

    assert response.status_code == 409
    assert response.data["code"] == "cluster_health_probe_unavailable"
    assert ClusterHealthObservation.objects.get(cluster=cluster).outcome == "configuration_unavailable"
    assert PlatformAuditEvent.objects.filter(action="cluster.health_checked", result="failed").exists()


def test_configuration_only_workspace_import_creates_pending_domains():
    owner = User.objects.create_user(
        username="import-owner", email="owner@example.test", password="secret",
    )
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    response = client_for(superuser).post(
        f"{CONTROL}workspaces/import-workspace/",
        {
            "confirm": True,
            "reason": "Restore reviewed workspace configuration",
            "format": "idlevo-workspace-v1",
            "workspace": {
                "name": "Restored Shop",
                "slug": "restored-shop",
                "email": "shop@example.test",
                "settings": {"locale": "en-NZ"},
            },
            "owner_email": owner.email,
            "custom_domains": [{"hostname": "restored.example.test"}],
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="import-key-0001",
    )

    assert response.status_code == 201
    workspace = Workspace.objects.get(slug="restored-shop")
    assert workspace.domains.get(hostname="restored.example.test").verification_status == "pending"
    audit = PlatformAuditEvent.objects.get(action="workspace.imported")
    assert audit.after["custom_domains"] == ["restored.example.test"]


def _placement_cluster(identifier, *, max_workspaces=10):
    return Cluster.objects.create(
        id=identifier,
        name=identifier.title(),
        region="apac",
        api_base_url=f"https://{identifier}.example.test",
        db_host="db.example.test",
        redis_url="rediss://redis.example.test",
        s3_bucket=f"{identifier}-workspaces",
        max_workspaces=max_workspaces,
    )


def test_placement_reservation_is_fenced_audited_and_reversible():
    workspace = Workspace.objects.create(name="Unplaced Shop", slug="unplaced-shop", is_active=True)
    target = _placement_cluster("target")
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)

    response = client.post(
        f"{CONTROL}placement-requests/",
        {
            "confirm": True,
            "reason": "Reserve capacity before verified placement",
            "workspace_id": workspace.id,
            "target_cluster_id": target.id,
            "expected_placement_fence": 0,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-key-0001",
    )

    assert response.status_code == 202
    assert response.data["status"] == "reserved"
    assert [event["event_type"] for event in response.data["events"]] == ["requested", "capacity_reserved"]
    placement = WorkspacePlacementRequest.objects.get()
    assert placement.workspace_id == workspace.id
    assert placement.target_cluster_id == target.id
    profile = WorkspacePlatformProfile.objects.get(workspace=workspace)
    assert profile.cluster_id is None
    assert profile.placement_fence == 1
    assert PlatformAuditEvent.objects.filter(action="workspace.placement_reserved", target_id=str(workspace.id)).exists()

    replay = client.post(
        f"{CONTROL}placement-requests/",
        {
            "confirm": True,
            "reason": "Reserve capacity before verified placement",
            "workspace_id": workspace.id,
            "target_cluster_id": target.id,
            "expected_placement_fence": 0,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-key-0001",
    )
    assert replay.status_code == 202
    assert replay["Idempotent-Replayed"] == "true"
    assert WorkspacePlacementRequest.objects.count() == 1

    queued = client.get(f"{CONTROL}placement-requests/?workspace={workspace.id}")
    assert queued.status_code == 200
    assert queued.data[0]["id"] == str(placement.id)

    rollback = client.post(
        f"{CONTROL}placement-requests/{placement.id}/rollback/",
        {"confirm": True, "reason": "Placement no longer required"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-rollback-0001",
    )
    assert rollback.status_code == 200
    assert rollback.data["status"] == "rolled_back"
    assert [event["event_type"] for event in rollback.data["events"]] == [
        "requested", "capacity_reserved", "rollback_requested", "capacity_released",
    ]
    profile.refresh_from_db()
    assert profile.cluster_id is None
    assert profile.placement_fence == 2


def test_placement_reservations_consume_capacity_without_changing_workspace_routing():
    target = _placement_cluster("single", max_workspaces=1)
    first = Workspace.objects.create(name="First", slug="first", is_active=True)
    second = Workspace.objects.create(name="Second", slug="second", is_active=True)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)

    first_response = client.post(
        f"{CONTROL}placement-requests/",
        {
            "confirm": True,
            "reason": "Reserve the only available slot",
            "workspace_id": first.id,
            "target_cluster_id": target.id,
            "expected_placement_fence": 0,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-capacity-0001",
    )
    assert first_response.status_code == 202

    refused = client.post(
        f"{CONTROL}placement-requests/",
        {
            "confirm": True,
            "reason": "Try to reserve capacity for another workspace",
            "workspace_id": second.id,
            "target_cluster_id": target.id,
            "expected_placement_fence": 0,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-capacity-0002",
    )
    assert refused.status_code == 409
    assert refused.data["code"] == "cluster_capacity_reserved"
    assert WorkspacePlatformProfile.objects.get(workspace=first).cluster_id is None
    assert not WorkspacePlatformProfile.objects.filter(workspace=second).exists()


def test_live_migration_request_is_refused_without_data_plane_adapter():
    source = _placement_cluster("source")
    target = _placement_cluster("target")
    workspace = Workspace.objects.create(name="Existing Shop", slug="existing-shop", is_active=True)
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=source)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    response = client_for(superuser).post(
        f"{CONTROL}placement-requests/",
        {
            "confirm": True,
            "reason": "Move workspace closer to customers",
            "workspace_id": workspace.id,
            "target_cluster_id": target.id,
            "expected_placement_fence": profile.placement_fence,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-migrate-0001",
    )

    assert response.status_code == 409
    assert response.data["code"] == "workspace_live_migration_unsupported"
    profile.refresh_from_db()
    assert profile.cluster_id == source.id
    assert not WorkspacePlacementRequest.objects.exists()
    assert PlatformAuditEvent.objects.filter(
        action="workspace.placement_reserved", result="failed", target_id=str(workspace.id),
    ).exists()


def test_expired_placement_reservation_is_released_fenced_and_audited():
    workspace = Workspace.objects.create(name="Expired Slot", slug="expired-slot", is_active=True)
    target = _placement_cluster("target")
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)
    created = client.post(
        f"{CONTROL}placement-requests/",
        {
            "confirm": True,
            "reason": "Reserve a slot for placement verification",
            "workspace_id": workspace.id,
            "target_cluster_id": target.id,
            "expected_placement_fence": 0,
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="placement-expiry-0001",
    )
    assert created.status_code == 202
    placement = WorkspacePlacementRequest.objects.get()
    placement.reservation_expires_at = timezone.now() - timedelta(seconds=1)
    placement.save(update_fields=["reservation_expires_at"])

    expired = expire_due_reservations(limit=10)

    assert [item.pk for item in expired] == [placement.pk]
    placement.refresh_from_db()
    profile = WorkspacePlatformProfile.objects.get(workspace=workspace)
    assert placement.status == "expired"
    assert profile.placement_fence == 2
    assert list(placement.events.values_list("event_type", flat=True)) == [
        "requested", "capacity_reserved", "reservation_expired",
    ]
    assert PlatformAuditEvent.objects.filter(
        action="workspace.placement_expired", target_id=str(workspace.id), result="succeeded",
    ).exists()


def test_placement_expiry_task_is_disabled_until_the_deployment_opts_in(settings):
    from bfg.platform.tasks import expire_placement_reservations

    settings.PLATFORM_PLACEMENT_EXPIRY_ENABLED = False

    assert expire_placement_reservations() == {"enabled": False, "expired": 0}


def test_workspace_import_refuses_a_cluster_that_is_not_accepting_new_workspaces():
    owner = User.objects.create_user(username="import-owner", email="owner@example.test", password="secret")
    Cluster.objects.create(
        id="closed", name="Closed", region="apac", api_base_url="https://api.example.test",
        db_host="db.example.test", redis_url="redis://redis.example.test", s3_bucket="closed",
        is_accepting_new=False,
    )
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")

    response = client_for(superuser).post(
        f"{CONTROL}workspaces/import-workspace/",
        {
            "confirm": True,
            "reason": "Reject an import into a closed cluster",
            "workspace": {"name": "Closed Cluster Shop", "slug": "closed-cluster-shop"},
            "owner_email": owner.email,
            "cluster": {"id": "closed"},
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="import-key-closed",
    )

    assert response.status_code == 409
    assert response.data["code"] == "workspace_cluster_unavailable"
    assert not Workspace.objects.filter(slug="closed-cluster-shop").exists()
    assert PlatformAuditEvent.objects.filter(action="workspace.imported", result="failed").exists()


def test_cluster_health_target_is_allowlisted_and_never_uses_an_ip_literal(settings):
    settings.CLUSTER_HEALTH_ALLOWED_HOSTS = ["api.uat.example.test"]
    cluster = Cluster(id="uat", name="UAT", region="apac", api_base_url="https://api.uat.example.test")
    assert cluster_health_url(cluster) == "https://api.uat.example.test/api/v1/health/"

    cluster.api_base_url = "https://127.0.0.1:8443/"
    with pytest.raises(ClusterHealthProbeConfigurationError):
        cluster_health_url(cluster)

    cluster.api_base_url = "https://api.uat.example.test/redirect?to=https://127.0.0.1/"
    with pytest.raises(ClusterHealthProbeConfigurationError):
        cluster_health_url(cluster)


def test_control_variable_write_is_audited_and_replayed():
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)
    url = f"{CONTROL}variables/grace_days/"
    payload = {"confirm": True, "value": 21, "reason": "Allow a longer payment grace period"}

    response = client.patch(url, payload, format="json", HTTP_X_IDEMPOTENCY_KEY="variable-key-0001")
    assert response.status_code == 200
    assert response.data["value"] == 21
    audit = PlatformAuditEvent.objects.get(action="configuration.variable_updated")
    assert audit.reason == payload["reason"]
    assert audit.before["value"] == 14
    assert audit.after["value"] == 21

    replay = client.patch(url, payload, format="json", HTTP_X_IDEMPOTENCY_KEY="variable-key-0001")
    assert replay.status_code == 200
    assert replay["Idempotent-Replayed"] == "true"
    assert PlatformAuditEvent.objects.filter(action="configuration.variable_updated").count() == 1


def test_control_meter_price_and_exchange_rate_writes_are_audited():
    for code, name in (("USD", "US Dollar"), ("NZD", "New Zealand Dollar")):
        Currency.objects.create(code=code, name=name, symbol=code, decimal_places=2, is_active=True)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)

    meter = client.post(
        f"{CONTROL}meter-prices/",
        {
            "confirm": True,
            "meter": "vendor.lookup",
            "vendor_cost": "0.15",
            "unit_size": 1000,
            "reason": "Vendor increased lookup costs",
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="meter-key-0001",
    )
    assert meter.status_code == 201
    assert PlatformAuditEvent.objects.filter(action="configuration.meter_price_added").exists()

    rate = client.post(
        f"{CONTROL}exchange-rates/",
        {
            "confirm": True,
            "from": "USD",
            "to": "NZD",
            "rate": "1.70",
            "reason": "Reference feed was unavailable",
        },
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="rate-key-0001",
    )
    assert rate.status_code == 201
    assert PlatformAuditEvent.objects.filter(action="configuration.exchange_rate_set").exists()


def test_control_usage_cap_and_base_plan_grant_are_audited_and_recoverable():
    workspace = Workspace.objects.create(name="Controlled Shop", slug="controlled-shop", is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=workspace)
    superuser = User.objects.create_superuser(username="root", email="root@example.test", password="secret")
    client = client_for(superuser)

    cap = client.patch(
        f"{CONTROL}workspaces/{workspace.id}/usage-cap/",
        {"confirm": True, "cap_points": "25", "reason": "Raise allowance for seasonal demand"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="cap-key-0001",
    )
    assert cap.status_code == 200
    assert cap.data["cap_points"] == "25.00"
    assert PlatformAuditEvent.objects.filter(action="workspace.usage_cap_updated").exists()

    granted = client.post(
        f"{CONTROL}workspaces/{workspace.id}/grants/",
        {"confirm": True, "key": "", "months": 1, "reason": "Include the base plan during migration"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="grant-key-0001",
    )
    assert granted.status_code == 201
    entitlement_id = granted.data["entitlement"]["id"]
    assert client.get(f"{CONTROL}workspaces/{workspace.id}/grants/").status_code == 200

    revoked = client.post(
        f"{CONTROL}workspaces/{workspace.id}/grants/{entitlement_id}/revoke/",
        {"confirm": True, "reason": "Migration plan was cancelled"},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="revoke-key-0001",
    )
    assert revoked.status_code == 200
    assert revoked.data["entitlement"]["status"] == "ended"
    assert PlatformAuditEvent.objects.filter(action="workspace.entitlement_revoked").exists()

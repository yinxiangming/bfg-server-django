import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import Workspace
from bfg.finance.models import Currency
from bfg.platform.models import Cluster, PlatformAuditEvent
from bfg.platform.models.workspace_profile import WorkspacePlatformProfile
from bfg.platform.services.cluster_health import (
    ClusterHealthProbeConfigurationError,
    cluster_health_url,
)


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

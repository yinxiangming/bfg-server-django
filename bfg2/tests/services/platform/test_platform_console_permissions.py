import pytest
from django.contrib.auth import get_user_model
from unittest.mock import patch
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, Workspace, WorkspaceDomain
from bfg.common.exceptions import WorkspaceCapacityUnavailable
from bfg.common.services.workspace_service import WorkspaceService
from bfg.platform.models import Cluster, PlatformAuditEvent
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile
from bfg.platform.serializers.workspace import WorkspaceCreateSerializer
from bfg.platform.services.workspace_service import is_platform_admin


User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/v1/platform/console/workspaces/",
    "/api/v1/platform/console/clusters/",
    "/api/v1/platform/console/audit-events/",
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
    }
    assert superuser_response.data["platform_capabilities"] == {
        "cluster_management": True,
        "audit_log": True,
        "configuration": False,
    }


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

    exported = client.get(f"/api/v1/platform/console/workspaces/{workspace.id}/export/")
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

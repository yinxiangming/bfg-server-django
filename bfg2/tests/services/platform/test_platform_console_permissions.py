import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, Workspace, WorkspaceDomain
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

from unittest.mock import patch
import uuid

import requests

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import Workspace, WorkspaceDomain
from bfg.platform.models import Cluster, PlatformMembership, WorkspacePlatformProfile
from bfg.platform.serializers.workspace import WorkspaceDetailSerializer


User = get_user_model()



def test_platform_workspaces_me_returns_resolved_domain_from_custom_primary(db, settings):
    settings.PLATFORM_EMBEDDED = False
    user = User.objects.create_user(username="pw-user", password="secret")
    workspace = Workspace.objects.create(name="Acme", slug="acme", is_active=True)
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="portal.acme.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1/platform/workspaces/me/")

    assert response.status_code == 200
    assert response.data["workspaces"][0]["domain"] == "portal.acme.test"



def test_platform_workspaces_me_returns_system_default_when_no_custom_primary(db, settings):
    settings.PLATFORM_EMBEDDED = False
    user = User.objects.create_user(username="pw-user-2", password="secret")
    workspace = Workspace.objects.create(name="Acme Two", slug="acme-two", is_active=True)
    cluster = Cluster.objects.create(
        name="Cluster Two",
        region="apac",
        api_base_url="http://api.example.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1/platform/workspaces/me/")

    assert response.status_code == 200
    assert response.data["workspaces"][0]["domain"] == "acme-two.shops.example.test"


def test_workspace_detail_serializer_includes_workspace_profile_data(db):
    workspace = Workspace.objects.create(name="Profile WS", slug="profile-ws", is_active=True)
    cluster = Cluster.objects.create(
        name="Cluster Profile",
        region="apac",
        api_base_url="http://api.profile.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    WorkspacePlatformProfile.objects.create(
        workspace=workspace,
        cluster=cluster,
        region="apac",
        remote_workspace_uuid=uuid.uuid4(),
    )
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="portal.profile.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    data = WorkspaceDetailSerializer(workspace).data

    assert data["workspace_profile"]["region"] == "apac"
    assert data["workspace_profile"]["workspace_api_url"] == "http://api.profile.test"
    assert data["workspace_profile"]["workspace_frontend_url"] == "https://portal.profile.test"
    assert data["workspace_profile"]["cluster"]["id"] == cluster.id
    assert data["workspace_profile"]["cluster"]["frontend_base_url"] == "https://shops.example.test"


@patch("bfg.platform.views.auth_views.http_requests.post")
def test_token_exchange_standalone_returns_custom_primary_frontend_url(mock_post, db, settings):
    settings.PLATFORM_EMBEDDED = False
    settings.PLATFORM_API_KEY = "test-platform-key"

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": "workspace-token", "workspace_id": 123, "workspace_uuid": str(uuid.uuid4())}

    mock_post.return_value = DummyResponse()

    user = User.objects.create_user(username="te-user", password="secret", email="te@example.com")
    workspace = Workspace.objects.create(name="Token WS", slug="token-ws", is_active=True)
    cluster = Cluster.objects.create(
        name="Cluster TE",
        region="apac",
        api_base_url="http://api.workspace.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="portal.token-ws.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post("/api/v1/platform/auth/token-exchange/", {"workspace_id": "token-ws"}, format="json")

    assert response.status_code == 200
    assert response.data["workspace_frontend_url"] == "https://portal.token-ws.test"
    assert response.data["workspace_url"] == "http://api.workspace.test"


@patch("bfg.platform.views.auth_views.http_requests.post")
def test_token_exchange_standalone_returns_system_default_frontend_url(mock_post, db, settings):
    settings.PLATFORM_EMBEDDED = False
    settings.PLATFORM_API_KEY = "test-platform-key"

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": "workspace-token", "workspace_id": 456, "workspace_uuid": str(uuid.uuid4())}

    mock_post.return_value = DummyResponse()

    user = User.objects.create_user(username="te-user-2", password="secret", email="te2@example.com")
    workspace = Workspace.objects.create(name="Token WS 2", slug="token-ws-2", is_active=True)
    cluster = Cluster.objects.create(
        name="Cluster TE 2",
        region="apac",
        api_base_url="http://api.workspace2.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post("/api/v1/platform/auth/token-exchange/", {"workspace_id": "token-ws-2"}, format="json")

    assert response.status_code == 200
    assert response.data["workspace_frontend_url"] == "https://token-ws-2.shops.example.test"
    assert response.data["workspace_url"] == "http://api.workspace2.test"


@patch("bfg.platform.views.auth_views.http_requests.post")
def test_token_exchange_does_not_disclose_remote_failure_details(mock_post, db, settings):
    settings.PLATFORM_EMBEDDED = False
    mock_post.side_effect = requests.RequestException("connection to https://private.cluster.test:9443 failed")

    user = User.objects.create_user(username="token-error", password="secret", email="token-error@example.com")
    workspace = Workspace.objects.create(name="Token Error", slug="token-error", is_active=True)
    cluster = Cluster.objects.create(
        name="Token Error Cluster",
        region="apac",
        api_base_url="https://private.cluster.test:9443",
        frontend_base_url="https://shops.example.test",
        db_host="private-db.example.test",
        redis_url="rediss://private-redis.example.test",
        s3_bucket="token-error",
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post("/api/v1/platform/auth/token-exchange/", {"workspace_id": workspace.slug}, format="json")

    assert response.status_code == 502
    assert response.data == {"error": "Unable to reach the workspace server. Please try again."}
    assert "private.cluster.test" not in str(response.data)

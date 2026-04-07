from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import Workspace, WorkspaceDomain
from bfg.platform.models import Cluster, PlatformMembership, WorkspacePlatformProfile


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

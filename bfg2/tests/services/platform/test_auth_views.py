from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import Workspace, WorkspaceDomain
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile


User = get_user_model()



def test_sso_start_uses_workspace_domain_resolver(db):
    user = User.objects.create_user(username="member", password="secret")
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
    response = client.post(
        "/api/v1/platform/auth/sso/start/",
        {"workspace_id": "acme", "next": "/admin/orders"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["redirect_url"].startswith("https://portal.acme.test/auth/sso?code=")



def test_sso_start_returns_400_when_workspace_has_no_public_domain(db):
    user = User.objects.create_user(username="member2", password="secret")
    workspace = Workspace.objects.create(name="No Domain", slug="no-domain", is_active=True)
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/v1/platform/auth/sso/start/",
        {"workspace_id": "no-domain", "next": "/admin"},
        format="json",
    )

    assert response.status_code == 400
    assert "public frontend domain" in response.data["error"]

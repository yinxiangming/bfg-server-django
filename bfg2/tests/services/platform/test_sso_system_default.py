from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import Workspace, WorkspaceDomain
from bfg.platform.models import Cluster, PlatformMembership, WorkspacePlatformProfile


User = get_user_model()



def test_sso_start_uses_system_default_when_no_custom_primary(db, settings):
    settings.PLATFORM_EMBEDDED = False
    user = User.objects.create_user(username="member-sd", password="secret")
    workspace = Workspace.objects.create(name="SD Workspace", slug="sd-workspace", is_active=True)
    cluster = Cluster.objects.create(
        name="Cluster SD",
        region="apac",
        api_base_url="http://api.sd.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/v1/platform/auth/sso/start/",
        {"workspace_id": "sd-workspace", "next": "/admin/orders"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["redirect_url"].startswith("https://sd-workspace.shops.example.test/auth/sso?code=")

from datetime import timedelta
from unittest.mock import patch

import requests

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.models import Workspace, WorkspaceDomain
from bfg.platform.models import Cluster, PlatformMembership, PlatformSSOCode, WorkspacePlatformProfile


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
    assert response.data == {"error": "The workspace does not have a verified public domain."}


def test_sso_exchange_atomically_consumes_code_once(db, settings):
    settings.PLATFORM_EMBEDDED = True
    user = User.objects.create_user(username="exchange-member", password="secret")
    workspace = Workspace.objects.create(
        name="Exchange Workspace",
        slug="exchange-workspace",
        is_active=True,
    )
    sso_code = PlatformSSOCode.objects.create(
        workspace=workspace,
        user=user,
        next_url="/admin",
        redirect_domain="https://workspace.example.test",
    )
    client = APIClient()

    accepted = client.post(
        "/api/v1/platform/auth/sso/exchange/",
        {"code": sso_code.code},
        format="json",
    )
    replayed = client.post(
        "/api/v1/platform/auth/sso/exchange/",
        {"code": sso_code.code},
        format="json",
    )

    assert accepted.status_code == 200
    assert accepted.data["workspace"]["id"] == workspace.id
    assert replayed.status_code == 400
    assert replayed.data == {"error": "SSO code has already been used"}
    sso_code.refresh_from_db()
    assert sso_code.used_at is not None


def test_sso_exchange_does_not_consume_expired_code(db, settings):
    settings.PLATFORM_EMBEDDED = True
    user = User.objects.create_user(username="expired-member", password="secret")
    workspace = Workspace.objects.create(
        name="Expired Workspace",
        slug="expired-workspace",
        is_active=True,
    )
    sso_code = PlatformSSOCode.objects.create(
        workspace=workspace,
        user=user,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = APIClient().post(
        "/api/v1/platform/auth/sso/exchange/",
        {"code": sso_code.code},
        format="json",
    )

    assert response.status_code == 400
    assert response.data == {"error": "SSO code has expired"}
    sso_code.refresh_from_db()
    assert sso_code.used_at is None


@patch("bfg.platform.views.auth_views.http_requests.post")
def test_standalone_sso_exchange_releases_code_after_remote_failure(mock_post, db, settings):
    settings.PLATFORM_EMBEDDED = False
    mock_post.side_effect = requests.RequestException("connection to https://private.cluster.test:9443 failed")
    user = User.objects.create_user(username="retry-member", password="secret", email="retry@example.test")
    workspace = Workspace.objects.create(name="Retry Workspace", slug="retry-workspace", is_active=True)
    cluster = Cluster.objects.create(
        name="Retry Cluster",
        region="apac",
        api_base_url="https://private.cluster.test:9443",
        frontend_base_url="https://shops.example.test",
        db_host="private-db.example.test",
        redis_url="rediss://private-redis.example.test",
        s3_bucket="retry-workspace",
    )
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, cluster=cluster, region="apac")
    PlatformMembership.objects.create(user=user, profile=profile, role="owner", is_active=True)
    sso_code = PlatformSSOCode.objects.create(workspace=workspace, user=user, next_url="/admin")

    response = APIClient().post(
        "/api/v1/platform/auth/sso/exchange/",
        {"code": sso_code.code},
        format="json",
    )

    assert response.status_code == 502
    assert response.data == {"error": "Unable to reach the workspace server. Please try again."}
    assert "private.cluster.test" not in str(response.data)
    sso_code.refresh_from_db()
    assert sso_code.used_at is None

from django.contrib.auth import get_user_model

from bfg.common.models import (
    WorkspaceDomain,
    ensure_system_default_workspace_domain,
    resolve_workspace_public_frontend_base_url,
    upsert_custom_workspace_domain,
)
from bfg.common.services.workspace_service import WorkspaceService
from bfg.platform.models import Cluster, WorkspacePlatformProfile


User = get_user_model()


def test_create_workspace_ensures_platform_profile(db):
    user = User.objects.create_user(username="owner", password="x")
    service = WorkspaceService(workspace=None, user=user)

    workspace = service.create_workspace(name="Acme", slug="acme", owner_user=user, region="apac")

    profile = WorkspacePlatformProfile.objects.get(workspace=workspace)
    assert profile.region == "apac"


def test_create_workspace_with_cluster_materializes_system_default_domain(db):
    user = User.objects.create_user(username="owner2", password="x")
    cluster = Cluster.objects.create(
        name="NZ Cluster",
        region="apac",
        api_base_url="http://api.example.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    service = WorkspaceService(workspace=None, user=user)

    workspace = service.create_workspace(
        name="Acme Two",
        slug="acme-two",
        owner_user=user,
        region="apac",
        cluster=cluster,
    )

    domain = WorkspaceDomain.objects.get(workspace=workspace, kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT)
    assert domain.hostname == "acme-two.shops.example.test"
    assert domain.verification_status == WorkspaceDomain.VERIFICATION_VERIFIED
    assert domain.is_primary is False


def test_resolve_workspace_public_frontend_base_url_prefers_primary_custom_domain(db):
    user = User.objects.create_user(username="owner3", password="x")
    cluster = Cluster.objects.create(
        name="US Cluster",
        region="us",
        api_base_url="http://api.example.test",
        frontend_base_url="https://workspace.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    service = WorkspaceService(workspace=None, user=user)
    workspace = service.create_workspace(name="Acme Three", slug="acme-three", owner_user=user, cluster=cluster)

    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="store.acme.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    assert resolve_workspace_public_frontend_base_url(workspace) == "https://store.acme.test"


def test_upsert_custom_workspace_domain_demotes_previous_primary(db):
    user = User.objects.create_user(username="owner4", password="x")
    service = WorkspaceService(workspace=None, user=user)
    workspace = service.create_workspace(name="Acme Four", slug="acme-four", owner_user=user)

    first = upsert_custom_workspace_domain(
        workspace,
        "one.acme.test",
        is_primary=True,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
    )
    second = upsert_custom_workspace_domain(
        workspace,
        "two.acme.test",
        is_primary=True,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_primary is False
    assert second.is_primary is True


def test_ensure_system_default_workspace_domain_replaces_stale_entry(db):
    user = User.objects.create_user(username="owner5", password="x")
    cluster = Cluster.objects.create(
        name="Cluster Five",
        region="apac",
        api_base_url="http://api.example.test",
        frontend_base_url="https://shops.example.test",
        max_workspaces=100,
        current_workspaces=0,
        is_active=True,
    )
    service = WorkspaceService(workspace=None, user=user)
    workspace = service.create_workspace(name="Acme Five", slug="acme-five", owner_user=user, cluster=cluster)

    domain = WorkspaceDomain.objects.get(workspace=workspace, kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT)
    domain.hostname = "old.example.test"
    domain.save(update_fields=["hostname", "updated_at"])

    refreshed = ensure_system_default_workspace_domain(workspace)
    assert refreshed.hostname == "acme-five.shops.example.test"
    assert workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).count() == 1

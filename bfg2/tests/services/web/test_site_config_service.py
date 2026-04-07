from types import SimpleNamespace

from bfg.common.models import WorkspaceDomain
from bfg.web.services.site_config_service import SiteConfigService


def test_upsert_site_returns_none_for_empty_payload():
    service = SiteConfigService(workspace=SimpleNamespace(id=1), user=None)
    assert service._upsert_site(None) is None


def test_sync_workspace_custom_domain_upserts_workspace_domain(db):
    workspace = SimpleNamespace(id=1)
    workspace.pk = 1
    workspace.domains = WorkspaceDomain.objects.none()
    service = SiteConfigService(workspace=workspace, user=None)

    from bfg.common.models import Workspace
    real_workspace = Workspace.objects.create(name="Site WS", slug="site-ws", is_active=True)
    service.workspace = real_workspace

    service._sync_workspace_custom_domain({"domain": "https://Shop.Example.test:443"})

    domain = WorkspaceDomain.objects.get(workspace=real_workspace, hostname="shop.example.test")
    assert domain.kind == WorkspaceDomain.KIND_CUSTOM
    assert domain.is_primary is True

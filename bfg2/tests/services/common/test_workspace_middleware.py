from django.core.cache import cache
from django.test import RequestFactory

from bfg.common.middleware import _get_workspace_by_domain, invalidate_workspace_cache
from bfg.common.storefront_cache import storefront_config_cache_key
from bfg.common.models import Workspace, WorkspaceDomain



def test_get_workspace_by_domain_resolves_only_via_workspace_domain(db):
    workspace = Workspace.objects.create(name="Acme", slug="acme", is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="shop.acme.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    resolved = _get_workspace_by_domain("shop.acme.test")
    assert resolved.id == workspace.id



def test_get_workspace_by_domain_caches_workspace(db):
    workspace = Workspace.objects.create(name="Beta", slug="beta", is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="beta.example.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    cache.clear()
    resolved = _get_workspace_by_domain("beta.example.test")
    assert resolved.id == workspace.id
    assert cache.get("workspace:domain:beta.example.test").id == workspace.id


def test_invalidate_workspace_cache_clears_storefront_config_entries(db):
    workspace = Workspace.objects.create(name="Gamma", slug="gamma", is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname="gamma.example.test",
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )

    cache.clear()
    cache.set(storefront_config_cache_key(workspace.id, "en"), {"workspace_domain": "old.test"}, 3600)
    cache.set(storefront_config_cache_key(workspace.id, "zh-hans"), {"workspace_domain": "old.test"}, 3600)
    cache.set(f"workspace:id:{workspace.id}", workspace, 600)

    invalidate_workspace_cache(workspace)

    assert cache.get(storefront_config_cache_key(workspace.id, "en")) is None
    assert cache.get(storefront_config_cache_key(workspace.id, "zh-hans")) is None
    assert cache.get(storefront_config_cache_key(workspace.id, "zh-hant")) is None
    assert cache.get(f"workspace:id:{workspace.id}") is None

from types import SimpleNamespace

from bfg.web.services.site_config_service import SiteConfigService


def test_upsert_site_returns_none_for_empty_payload():
    service = SiteConfigService(workspace=SimpleNamespace(id=1), user=None)
    assert service._upsert_site(None) is None

from types import SimpleNamespace

from bfg.web.services.site_service import SiteService


def test_deactivate_site_sets_is_active_false():
    service = SiteService(workspace=SimpleNamespace(id=1), user=None)
    site = SimpleNamespace(workspace_id=1, is_active=True)
    state = {"saved": False}
    site.save = lambda: state.update({"saved": True})

    result = service.deactivate_site(site)
    assert result.is_active is False
    assert state["saved"] is True

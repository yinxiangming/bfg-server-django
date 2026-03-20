from types import SimpleNamespace

from bfg.shop.services.batch_service import is_batch_management_enabled


def test_is_batch_management_enabled_by_workspace_flag(monkeypatch):
    monkeypatch.setattr("bfg.shop.services.batch_service.settings.BFG2_SETTINGS", {}, raising=False)
    workspace = SimpleNamespace(settings={"features": {"batch_management": True}})
    assert is_batch_management_enabled(workspace) is True


def test_is_batch_management_enabled_by_global_setting(monkeypatch):
    monkeypatch.setattr(
        "bfg.shop.services.batch_service.settings.BFG2_SETTINGS",
        {"ENABLE_BATCH_MANAGEMENT": True},
        raising=False,
    )
    assert is_batch_management_enabled(None) is True

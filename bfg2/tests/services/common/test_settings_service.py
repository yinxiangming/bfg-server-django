from bfg.common.services.settings_service import SettingsService


def test_is_feature_enabled_reads_feature_map():
    service = SettingsService(workspace=None, user=None)
    settings = type("S", (), {"features": {"shop": True, "blog": False}})()

    assert service.is_feature_enabled(settings, "shop") is True
    assert service.is_feature_enabled(settings, "blog") is False

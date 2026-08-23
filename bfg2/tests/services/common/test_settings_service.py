from bfg.common.services.settings_service import SettingsService


def test_is_feature_enabled_reads_feature_map():
    service = SettingsService(workspace=None, user=None)
    settings = type("S", (), {"features": {"shop": True, "blog": False}})()

    assert service.is_feature_enabled(settings, "shop") is True
    assert service.is_feature_enabled(settings, "blog") is False


def test_new_settings_do_not_inherit_one_markets_currency(db):
    """
    `get_or_create_settings` seeded 'NZD' — the market the platform's first tenant sold
    in — which also overrode the model field's own default. A workspace that has not
    chosen a currency should get the library's neutral code default, not somebody else's.
    """
    from bfg.common.constants import DEFAULT_CURRENCY_CODE
    from bfg.common.models import Settings, Workspace

    workspace = Workspace.objects.create(name='Fresh', slug='fresh-ws', is_active=True)
    Settings.objects.filter(workspace=workspace).delete()

    settings = SettingsService(workspace=workspace, user=None).get_or_create_settings(workspace)

    assert settings.default_currency == DEFAULT_CURRENCY_CODE
    assert DEFAULT_CURRENCY_CODE != 'NZD'


def test_an_existing_currency_choice_is_left_alone(db):
    from bfg.common.models import Settings, Workspace

    workspace = Workspace.objects.create(name='Chosen', slug='chosen-ws', is_active=True)
    Settings.objects.update_or_create(workspace=workspace, defaults={'default_currency': 'NZD'})

    settings = SettingsService(workspace=workspace, user=None).get_or_create_settings(workspace)

    assert settings.default_currency == 'NZD'

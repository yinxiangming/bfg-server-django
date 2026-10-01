from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from config.local_apps import apply_local_app_settings


def contribute(namespace, modules):
    with patch('importlib.util.find_spec', side_effect=lambda name: object() if name in modules else None), patch('importlib.import_module', side_effect=modules.__getitem__):
        apply_local_app_settings(namespace, ['apps.alpha', 'apps.beta'])


def test_only_installed_contributions_are_loaded_and_host_values_preserved():
    target = {'SECRET_KEY': 'host', 'BFG_EXTRA_PUBLIC_PATHS': ()}
    contribute(target, {'apps.alpha.host_settings': SimpleNamespace(SETTINGS={'ALPHA_TOKEN': 'value'}, PUBLIC_PATHS=('/api/v1/alpha/',))})
    assert target == {'SECRET_KEY': 'host', 'ALPHA_TOKEN': 'value', 'BFG_EXTRA_PUBLIC_PATHS': ('/api/v1/alpha/',)}


@pytest.mark.parametrize('module', [
    SimpleNamespace(SETTINGS={'SECRET_KEY': 'override'}),
    SimpleNamespace(SETTINGS={'lower': 'bad'}),
    SimpleNamespace(SETTINGS=[]),
    SimpleNamespace(PUBLIC_PATHS=('/api/v1/beta/',)),
    SimpleNamespace(PUBLIC_PATHS=('/api/v1/alpha/../beta/',)),
    SimpleNamespace(PUBLIC_PATHS='/api/v1/alpha/'),
])
def test_invalid_contributions_leave_namespace_unchanged(module):
    target = {'SECRET_KEY': 'host', 'BFG_EXTRA_PUBLIC_PATHS': ()}
    with pytest.raises(ImproperlyConfigured):
        contribute(target, {'apps.alpha.host_settings': module})
    assert target == {'SECRET_KEY': 'host', 'BFG_EXTRA_PUBLIC_PATHS': ()}


def test_duplicate_extension_settings_fail_atomically():
    target = {'BFG_EXTRA_PUBLIC_PATHS': ()}
    modules = {f'apps.{name}.host_settings': SimpleNamespace(SETTINGS={'SHARED_TOKEN': name}) for name in ('alpha', 'beta')}
    with pytest.raises(ImproperlyConfigured):
        contribute(target, modules)
    assert target == {'BFG_EXTRA_PUBLIC_PATHS': ()}

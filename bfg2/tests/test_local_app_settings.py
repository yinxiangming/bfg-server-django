from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from config.local_apps import apply_local_app_settings, get_local_app_middleware


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


def test_app_without_host_settings_registers_no_middleware():
    with patch('importlib.util.find_spec', return_value=None):
        assert get_local_app_middleware(['apps.alpha']) == []


def test_app_owned_middleware_is_registered_in_declared_order():
    module = SimpleNamespace(MIDDLEWARE=[
        'apps.alpha.middleware.First',
        'apps.alpha.middleware.Second',
    ])
    with patch('importlib.util.find_spec', return_value=object()), \
            patch('importlib.import_module', return_value=module):
        assert get_local_app_middleware(['apps.alpha']) == [
            'apps.alpha.middleware.First',
            'apps.alpha.middleware.Second',
        ]


def test_middleware_discovery_does_not_hide_internal_import_errors():
    with patch('importlib.util.find_spec', side_effect=ImportError('broken dependency')):
        with pytest.raises(ImportError, match='broken dependency'):
            get_local_app_middleware(['apps.alpha'])


@pytest.mark.parametrize('declared', [
    'apps.alpha.middleware.Guard',
    ('apps.beta.middleware.Guard',),
    (object(),),
    ('apps.alpha..Guard',),
    ('apps.alpha.middleware.Guard', 'apps.alpha.middleware.Guard'),
])
def test_invalid_app_middleware_is_rejected(declared):
    module = SimpleNamespace(MIDDLEWARE=declared)
    with patch('importlib.util.find_spec', return_value=object()), \
            patch('importlib.import_module', return_value=module), \
            pytest.raises(ImproperlyConfigured):
        get_local_app_middleware(['apps.alpha'])

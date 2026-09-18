"""Which extensions a workspace uses, and what switching one on or off does.

Manifests are faked: the registry's discovery is swapped for a fixed set, so nothing
here depends on which apps a deployment happens to install.
"""

import sys
import types
from dataclasses import replace
from io import StringIO

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import CommandError, call_command
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from bfg.common.extensions import permissions as extension_permissions
from bfg.common.extensions import listen_for, registry, services
from bfg.common.extensions.permissions import RequiresExtension
from bfg.common.extensions.manifest import (
    ACTIVATION_PLATFORM_ADMIN,
    ACTIVATION_SYSTEM,
    ACTIVATION_WORKSPACE_OWNER,
    SCOPE_PLATFORM,
    SCOPE_TOOLING,
    SURFACE_ADMIN,
    SURFACE_STOREFRONT,
    VISIBILITY_INTERNAL,
    VISIBILITY_PRIVATE,
    ExtensionManifest,
    Prerequisite,
)
from bfg.common.models import StaffMember, StaffRole, User, Workspace, WorkspaceExtension

REAL_DISCOVER = registry._discover
HOOK_CALLS = []


def _clean_reviews_config(config):
    per_page = config.get('per_page', 10)
    if not isinstance(per_page, int) or not 1 <= per_page <= 50:
        raise ValueError('per_page must be a whole number from 1 to 50.')
    return {'per_page': per_page}


MANIFESTS = {
    'reviews': ExtensionManifest(
        key='reviews',
        name='Reviews',
        surfaces=(SURFACE_ADMIN, SURFACE_STOREFRONT),
        clean_config=_clean_reviews_config,
        on_activate=lambda workspace, record: HOOK_CALLS.append(('activate', workspace.id, record.key)),
        on_deactivate=lambda workspace, record: HOOK_CALLS.append(('deactivate', workspace.id, record.key)),
        app_label='reviews_app',
    ),
    'review_insights': ExtensionManifest(
        key='review_insights',
        name='Review insights',
        surfaces=(SURFACE_ADMIN,),
        requires=('reviews',),
        app_label='insights_app',
    ),
    'maps': ExtensionManifest(
        key='maps',
        name='Maps',
        surfaces=(SURFACE_STOREFRONT,),
        prerequisites=(
            Prerequisite(
                code='setting:MAPS_KEY',
                message='MAPS_KEY is not configured.',
                check=lambda workspace: bool(getattr(django_settings, 'MAPS_KEY', '')),
            ),
        ),
        app_label='maps_app',
    ),
    'sign_in': ExtensionManifest(key='sign_in', name='Sign-in', scope=SCOPE_PLATFORM, app_label='sign_in_app'),
    'importer': ExtensionManifest(key='importer', name='Importer', scope=SCOPE_TOOLING, app_label='importer_app'),
    'brand_portal': ExtensionManifest(
        key='brand_portal',
        name='Brand portal',
        visibility=VISIBILITY_PRIVATE,
        activation_policy=ACTIVATION_PLATFORM_ADMIN,
        app_label='brand_portal_app',
    ),
    'maintenance': ExtensionManifest(
        key='maintenance',
        name='Maintenance',
        visibility=VISIBILITY_INTERNAL,
        activation_policy=ACTIVATION_SYSTEM,
        app_label='maintenance_app',
    ),
}


@pytest.fixture(autouse=True)
def fake_manifests(monkeypatch):
    monkeypatch.setattr(registry, '_discover', lambda: dict(MANIFESTS))
    registry.reset_cache()
    services._load_entitlement_check.cache_clear()
    cache.clear()
    HOOK_CALLS.clear()
    yield
    registry.reset_cache()
    cache.clear()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Extensions WS', slug='extensions-ws', is_active=True)


def _member(workspace, username, role_code):
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code=role_code, defaults={'name': role_code.title()}
    )
    user = User.objects.create_user(username=username, email=f'{username}@example.com', password='x')
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


def _client(workspace, user=None):
    api = APIClient()
    if user is not None:
        api.force_authenticate(user=user)
    api.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return api


def _fake_app(monkeypatch, name, manifest=None):
    module = types.ModuleType(f'{name}.extension')
    if manifest is not None:
        module.EXTENSION = manifest
    monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, f'{name}.extension', module)
    return types.SimpleNamespace(name=name, label=name.replace('_app', ''))


# ── Manifests and discovery ──────────────────────────────────────────


def test_discovery_reads_the_extension_module_of_each_installed_app(monkeypatch, caplog):
    installed = [
        _fake_app(monkeypatch, 'gallery_app', ExtensionManifest(key='gallery', name='Gallery')),
        _fake_app(monkeypatch, 'broken_app'),
        types.SimpleNamespace(name='plain_app', label='plain'),
    ]
    monkeypatch.setitem(sys.modules, 'plain_app', types.ModuleType('plain_app'))
    monkeypatch.setattr(registry.apps, 'get_app_configs', lambda: installed)

    found = REAL_DISCOVER()

    assert list(found) == ['gallery']
    assert found['gallery'].app_label == 'gallery'
    assert 'broken_app.extension defines no EXTENSION manifest' in caplog.text


def test_discovery_keeps_the_first_of_two_manifests_with_one_key(monkeypatch, caplog):
    installed = [
        _fake_app(monkeypatch, 'first_app', ExtensionManifest(key='gallery', name='Gallery')),
        _fake_app(monkeypatch, 'second_app', ExtensionManifest(key='gallery', name='Another gallery')),
    ]
    monkeypatch.setattr(registry.apps, 'get_app_configs', lambda: installed)

    found = REAL_DISCOVER()

    assert found['gallery'].app_label == 'first'
    assert "Extension key 'gallery' is declared by both first and second" in caplog.text


def test_a_manifest_rejects_keys_that_cannot_be_used_in_urls():
    with pytest.raises(ValueError):
        ExtensionManifest(key='Reviews-2', name='Reviews')


def test_pricing_defaults_to_add_on_for_workspace_extensions_and_core_for_the_rest():
    assert ExtensionManifest(key='gallery', name='Gallery').pricing == 'addon'
    assert ExtensionManifest(key='gallery', name='Gallery', scope=SCOPE_PLATFORM).pricing == 'core'


def test_only_workspace_extensions_can_require_others():
    with pytest.raises(ValueError):
        ExtensionManifest(key='gallery', name='Gallery', scope=SCOPE_PLATFORM, requires=('reviews',))


def test_display_fields_are_optional():
    manifest = ExtensionManifest(key='gallery', name='Gallery')

    assert (manifest.name_zh, manifest.description_zh, manifest.icon, manifest.admin_url) == ('', '', '', '')


def test_a_default_storefront_skin_must_be_declared_by_the_manifest():
    with pytest.raises(ValueError, match='not declared'):
        ExtensionManifest(key='gallery', name='Gallery', default_storefront_skin='gallery')

    manifest = ExtensionManifest(
        key='gallery',
        name='Gallery',
        storefront_skins=('gallery',),
        default_storefront_skin='gallery',
    )
    assert manifest.storefront_skins == ('gallery',)

    with pytest.raises(ValueError, match='sequence'):
        ExtensionManifest(key='gallery', name='Gallery', storefront_skins='gallery')

    with pytest.raises(ValueError, match='invalid storefront skin'):
        ExtensionManifest(key='gallery', name='Gallery', storefront_skins=('gallery', 1))


def test_manifest_access_policies_default_to_public_and_workspace_owner():
    manifest = ExtensionManifest(key='gallery', name='Gallery')

    assert manifest.visibility == 'public'
    assert manifest.activation_policy == ACTIVATION_WORKSPACE_OWNER


@pytest.mark.parametrize(
    'fields',
    [
        {'visibility': 'secret'},
        {'activation_policy': 'operator'},
        {'visibility': VISIBILITY_PRIVATE},
        {'visibility': VISIBILITY_INTERNAL, 'activation_policy': ACTIVATION_PLATFORM_ADMIN},
    ],
)
def test_manifest_rejects_invalid_access_policy_combinations(fields):
    with pytest.raises(ValueError):
        ExtensionManifest(key='gallery', name='Gallery', **fields)


@pytest.mark.parametrize(
    'admin_url',
    [
        'admin/gallery',
        'https://example.com/admin/gallery',
        '//example.com/admin/gallery',
        # Browsers read a backslash in a URL as a slash, so this names a host as well.
        '/\\example.com/admin/gallery',
    ],
)
def test_an_admin_url_must_be_a_path_that_names_no_host(admin_url):
    with pytest.raises(ValueError, match='admin_url'):
        ExtensionManifest(key='gallery', name='Gallery', admin_url=admin_url)


# ── Availability ─────────────────────────────────────────────────────


def test_platform_and_tooling_extensions_are_always_available(workspace):
    assert services.available_keys(workspace) == {'sign_in', 'importer'}
    assert services.is_available(workspace, 'sign_in')
    assert services.is_available(None, 'sign_in')
    assert not services.is_available(workspace, 'reviews')
    assert not services.is_available(workspace, 'not_deployed')


def test_restricted_extensions_never_leak_into_client_availability(workspace):
    WorkspaceExtension.all_objects.create(
        workspace=workspace,
        key='brand_portal',
        status=WorkspaceExtension.STATUS_ACTIVE,
    )

    assert 'brand_portal' in services.available_keys(workspace)
    assert services.availability(workspace) == {
        'available': ['importer', 'sign_in'],
        'offered': ['maps', 'review_insights', 'reviews'],
    }
    assert 'brand_portal' not in str(services.availability(workspace, public_only=True))


@pytest.mark.parametrize(
    ('key', 'actor', 'allowed'),
    [
        ('reviews', ACTIVATION_WORKSPACE_OWNER, True),
        ('brand_portal', ACTIVATION_WORKSPACE_OWNER, False),
        ('brand_portal', ACTIVATION_PLATFORM_ADMIN, True),
        ('maintenance', ACTIVATION_PLATFORM_ADMIN, False),
        ('maintenance', ACTIVATION_SYSTEM, True),
    ],
)
def test_service_layer_enforces_extension_management_policy(key, actor, allowed):
    manifest = MANIFESTS[key]

    assert services.can_manage(manifest, actor) is allowed
    if allowed:
        assert services.require_manageable(key, actor) is manifest
    else:
        with pytest.raises(services.ExtensionError) as refused:
            services.require_manageable(key, actor)
        assert refused.value.code == 'unknown_extension'


def test_a_record_without_a_deployed_manifest_is_not_available(workspace):
    WorkspaceExtension.all_objects.create(workspace=workspace, key='retired', status=WorkspaceExtension.STATUS_ACTIVE)

    assert 'retired' not in services.available_keys(workspace)


def test_an_extension_is_only_as_available_as_what_it_requires(workspace):
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_PAUSED)
    WorkspaceExtension.all_objects.create(
        workspace=workspace, key='review_insights', status=WorkspaceExtension.STATUS_ACTIVE
    )

    assert 'review_insights' not in services.available_keys(workspace)


def test_the_entitlement_check_decides_what_a_workspace_may_use(workspace, settings, monkeypatch):
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = 'deployment.entitlements.check'
    monkeypatch.setattr(
        services, '_load_entitlement_check', lambda path: (lambda ws, manifest: manifest.key != 'reviews')
    )

    with pytest.raises(services.ExtensionError) as error:
        services.activate(workspace, 'reviews')
    assert error.value.code == 'not_entitled'

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    assert 'reviews' not in services.compute_available_keys(workspace)


def test_a_broken_entitlement_check_makes_the_extension_unavailable(workspace, settings, monkeypatch, caplog):
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = 'deployment.entitlements.check'

    def billing_is_down(ws, manifest):
        raise RuntimeError('billing is down')

    monkeypatch.setattr(services, '_load_entitlement_check', lambda path: billing_is_down)
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)

    assert 'reviews' not in services.compute_available_keys(workspace)
    assert 'Entitlement check failed for extension reviews' in caplog.text


def test_scheduled_work_runs_only_for_active_workspaces_using_the_extension(workspace):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    closed = Workspace.objects.create(name='Closed', slug='closed-ws', is_active=False)
    for using in (workspace, closed):
        WorkspaceExtension.all_objects.create(workspace=using, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)

    assert services.workspaces_with('reviews') == [workspace]
    assert {workspace, other} <= set(services.workspaces_with('sign_in'))
    assert closed not in services.workspaces_with('sign_in')
    assert services.workspaces_with('not_deployed') == []


# ── Activation ───────────────────────────────────────────────────────


def test_activating_makes_the_extension_available_and_runs_its_hook(workspace, django_capture_on_commit_callbacks):
    admin = _member(workspace, 'owner', 'admin')

    with django_capture_on_commit_callbacks(execute=True):
        record = services.activate(workspace, 'reviews', user=admin)

    assert record.status == WorkspaceExtension.STATUS_ACTIVE
    assert record.status_changed_by == admin
    assert record.activated_at is not None
    assert HOOK_CALLS == [('activate', workspace.id, 'reviews')]
    assert 'reviews' in services.available_keys(workspace)


def test_activation_applies_the_manifest_default_skin_only_when_theme_is_empty(
    workspace, monkeypatch, django_capture_on_commit_callbacks,
):
    from bfg.common.models import Settings

    monkeypatch.setitem(
        MANIFESTS,
        'reviews',
        replace(
            MANIFESTS['reviews'],
            storefront_skins=('preloved',),
            default_storefront_skin='preloved',
        ),
    )
    registry.reset_cache()

    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')

    custom = Settings.objects.get(workspace=workspace).custom_settings
    assert custom['storefront_ui']['theme'] == 'preloved'


def test_activation_default_skin_invalidates_a_cached_storefront_config(
    workspace, monkeypatch, django_capture_on_commit_callbacks,
):
    api = _client(workspace)
    assert api.get('/api/v1/settings/storefront/').json()['theme'] == 'store'
    monkeypatch.setitem(
        MANIFESTS,
        'reviews',
        replace(
            MANIFESTS['reviews'],
            storefront_skins=('preloved',),
            default_storefront_skin='preloved',
        ),
    )
    registry.reset_cache()

    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')

    assert api.get('/api/v1/settings/storefront/').json()['theme'] == 'preloved'


def test_activation_never_replaces_an_existing_workspace_theme(
    workspace, monkeypatch, django_capture_on_commit_callbacks,
):
    from bfg.common.models import Settings

    settings_obj = Settings.objects.get(workspace=workspace)
    settings_obj.custom_settings = {'storefront_ui': {'theme': 'website', 'header': 'compact'}}
    settings_obj.save(update_fields=['custom_settings'])
    monkeypatch.setitem(
        MANIFESTS,
        'reviews',
        replace(
            MANIFESTS['reviews'],
            storefront_skins=('preloved',),
            default_storefront_skin='preloved',
        ),
    )
    registry.reset_cache()

    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')

    assert Settings.objects.get(workspace=workspace).custom_settings == {
        'storefront_ui': {'theme': 'website', 'header': 'compact'},
    }


def test_the_cached_answer_is_dropped_when_the_change_commits(workspace, django_capture_on_commit_callbacks):
    assert 'reviews' not in services.available_keys(workspace)

    with django_capture_on_commit_callbacks() as callbacks:
        services.activate(workspace, 'reviews')
    assert 'reviews' not in services.available_keys(workspace)

    for callback in callbacks:
        callback()
    assert 'reviews' in services.available_keys(workspace)


def test_activating_an_active_extension_changes_nothing(workspace, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        first = services.activate(workspace, 'reviews')
        second = services.activate(workspace, 'reviews')

    assert first.pk == second.pk
    assert HOOK_CALLS == [('activate', workspace.id, 'reviews')]


def test_configuring_first_then_activating_uses_the_same_record(workspace, django_capture_on_commit_callbacks):
    configured = services.update_config(workspace, 'reviews', {'per_page': 25})
    assert configured.status == WorkspaceExtension.STATUS_INACTIVE

    with django_capture_on_commit_callbacks(execute=True):
        activated = services.activate(workspace, 'reviews')

    assert activated.pk == configured.pk
    assert (activated.status, activated.config) == (WorkspaceExtension.STATUS_ACTIVE, {'per_page': 25})
    assert HOOK_CALLS == [('activate', workspace.id, 'reviews')]


def test_an_extension_waits_for_what_it_requires(workspace, django_capture_on_commit_callbacks):
    with pytest.raises(services.ExtensionError) as error:
        services.activate(workspace, 'review_insights')
    assert error.value.code == 'requires_inactive'
    assert error.value.details == {'requires': ['reviews']}
    assert not WorkspaceExtension.all_objects.filter(workspace=workspace).exists()

    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')
        services.activate(workspace, 'review_insights')
    assert {'reviews', 'review_insights'} <= services.available_keys(workspace)


def test_unmet_prerequisites_block_activation(workspace, settings):
    with pytest.raises(services.ExtensionError) as error:
        services.activate(workspace, 'maps')
    assert error.value.code == 'prerequisite_failed'
    assert error.value.details == {'prerequisites': ['setting:MAPS_KEY']}

    settings.MAPS_KEY = 'configured'
    assert services.activate(workspace, 'maps').status == WorkspaceExtension.STATUS_ACTIVE


@pytest.mark.parametrize(
    'status, code',
    [
        (WorkspaceExtension.STATUS_ARCHIVING, 'busy'),
        (WorkspaceExtension.STATUS_RESTORING, 'busy'),
        (WorkspaceExtension.STATUS_ARCHIVED, 'archived'),
    ],
)
def test_extensions_being_archived_or_restored_cannot_be_activated(workspace, status, code):
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=status)

    with pytest.raises(services.ExtensionError) as error:
        services.activate(workspace, 'reviews')

    assert error.value.code == code


def test_only_deployed_workspace_extensions_can_be_switched(workspace):
    with pytest.raises(services.ExtensionError) as unknown:
        services.activate(workspace, 'not_deployed')
    assert unknown.value.code == 'unknown_extension'

    with pytest.raises(services.ExtensionError) as platform:
        services.deactivate(workspace, 'sign_in')
    assert platform.value.code == 'not_activatable'


def test_a_failing_activation_hook_leaves_the_state_unchanged(workspace, monkeypatch):
    def refuse(workspace, record):
        raise RuntimeError('provisioning failed')

    monkeypatch.setitem(MANIFESTS, 'reviews', replace(MANIFESTS['reviews'], on_activate=refuse))
    registry.reset_cache()

    with pytest.raises(RuntimeError):
        services.activate(workspace, 'reviews')
    assert not WorkspaceExtension.all_objects.filter(workspace=workspace, key='reviews').exists()


def test_clean_config_may_raise_a_django_validation_error(workspace, monkeypatch):
    def require_country(config):
        raise ValidationError('Pick a country.')

    monkeypatch.setitem(MANIFESTS, 'maps', replace(MANIFESTS['maps'], clean_config=require_country))
    registry.reset_cache()

    with pytest.raises(services.ExtensionError) as error:
        services.update_config(workspace, 'maps', {})

    assert (error.value.code, error.value.message) == ('invalid_config', 'Pick a country.')


# ── Deactivation ─────────────────────────────────────────────────────


def test_deactivation_waits_for_dependents_and_keeps_the_configuration(workspace, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews', config={'per_page': 20})
        services.activate(workspace, 'review_insights')

    with pytest.raises(services.ExtensionError) as error:
        services.deactivate(workspace, 'reviews')
    assert error.value.code == 'required_by_active'
    assert error.value.details == {'required_by': ['review_insights']}

    with django_capture_on_commit_callbacks(execute=True):
        services.deactivate(workspace, 'review_insights')
        record = services.deactivate(workspace, 'reviews')

    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert record.status_reason == 'deactivated'
    assert record.config == {'per_page': 20}
    assert ('deactivate', workspace.id, 'reviews') in HOOK_CALLS
    assert services.available_keys(workspace) == {'sign_in', 'importer'}


def test_a_failing_deactivation_hook_keeps_the_extension_active(workspace, monkeypatch, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')

    def refuse(workspace, record):
        raise RuntimeError('cleanup failed')

    monkeypatch.setitem(MANIFESTS, 'reviews', replace(MANIFESTS['reviews'], on_deactivate=refuse))
    registry.reset_cache()

    with pytest.raises(RuntimeError):
        services.deactivate(workspace, 'reviews')
    record = WorkspaceExtension.all_objects.get(workspace=workspace, key='reviews')
    assert record.status == WorkspaceExtension.STATUS_ACTIVE


# ── API ──────────────────────────────────────────────────────────────


def test_me_tells_staff_about_every_extension(workspace, django_capture_on_commit_callbacks):
    admin = _member(workspace, 'owner', 'admin')
    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')
        services.activate(workspace, 'review_insights')

    body = _client(workspace, admin).get('/api/v1/me/').json()

    assert body['extensions'] == {
        'available': ['importer', 'review_insights', 'reviews', 'sign_in'],
        'offered': ['maps', 'review_insights', 'reviews'],
    }


def test_me_tells_anyone_else_only_about_extensions_with_a_public_surface(
    workspace, django_capture_on_commit_callbacks
):
    shopper = User.objects.create_user(username='shopper', email='shopper@example.com', password='x')
    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')
        services.activate(workspace, 'review_insights')

    body = _client(workspace, shopper).get('/api/v1/me/').json()

    assert body['extensions'] == {'available': ['reviews'], 'offered': ['maps', 'reviews']}


def test_the_storefront_config_lists_only_extensions_with_a_public_surface(
    workspace, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')
        services.activate(workspace, 'review_insights')

    body = _client(workspace).get('/api/v1/settings/storefront/').json()

    assert body['extensions'] == {'available': ['reviews'], 'offered': ['maps', 'reviews']}


def test_a_cached_storefront_config_catches_up_once_activation_commits(
    workspace, django_capture_on_commit_callbacks
):
    api = _client(workspace)
    assert api.get('/api/v1/settings/storefront/').json()['extensions']['available'] == []

    with django_capture_on_commit_callbacks(execute=True):
        services.activate(workspace, 'reviews')

    assert api.get('/api/v1/settings/storefront/').json()['extensions']['available'] == ['reviews']


# ── Command ──────────────────────────────────────────────────────────


def _run_command(*args):
    out, err = StringIO(), StringIO()
    try:
        call_command('workspace_extensions', *args, stdout=out, stderr=err)
    except CommandError as exc:
        return out.getvalue(), err.getvalue(), str(exc)
    return out.getvalue(), err.getvalue(), None


def test_the_command_lists_what_each_workspace_uses(workspace):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    WorkspaceExtension.all_objects.create(
        workspace=other, key='review_insights', status=WorkspaceExtension.STATUS_PAUSED
    )

    out, _, error = _run_command('list')
    assert error is None
    assert [line.split() for line in out.splitlines()] == [
        ['EXTENSION', 'WORKSPACE', 'SLUG', 'STATUS', 'AVAILABLE'],
        ['review_insights', str(other.id), 'other-ws', 'paused', 'no'],
        ['reviews', str(workspace.id), 'extensions-ws', 'active', 'yes'],
    ]

    out, _, error = _run_command('list', '--workspace', 'extensions-ws')
    assert error is None
    assert [line.split() for line in out.splitlines()[1:]] == [
        ['brand_portal', str(workspace.id), 'extensions-ws', '-', 'no'],
        ['maintenance', str(workspace.id), 'extensions-ws', '-', 'no'],
        ['maps', str(workspace.id), 'extensions-ws', '-', 'no'],
        ['review_insights', str(workspace.id), 'extensions-ws', '-', 'no'],
        ['reviews', str(workspace.id), 'extensions-ws', 'active', 'yes'],
    ]


def test_the_command_switches_an_extension_for_several_workspaces(workspace):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)

    out, err, error = _run_command(
        'activate', 'reviews', '--workspace', str(workspace.id), '--workspace', 'other-ws'
    )
    assert (err, error) == ('', None)
    assert out.splitlines() == [
        f'{workspace.id} extensions-ws: reviews active',
        f'{other.id} other-ws: reviews active',
    ]
    assert 'reviews' in services.compute_available_keys(other)

    out, _, error = _run_command('deactivate', 'reviews', '--workspace', 'other-ws')
    assert error is None
    assert out.splitlines() == [f'{other.id} other-ws: reviews inactive']


def test_the_command_reports_refusals_without_holding_back_the_rest(workspace):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    WorkspaceExtension.all_objects.create(workspace=other, key='reviews', status=WorkspaceExtension.STATUS_ARCHIVED)

    out, err, error = _run_command('activate', 'reviews', '--workspace', 'other-ws', '--workspace', 'extensions-ws')

    assert error == '1 of 2 workspaces were not changed.'
    assert err.startswith(f'{other.id} other-ws: archived: ')
    assert out.splitlines() == [f'{workspace.id} extensions-ws: reviews active']


def test_the_command_changes_nothing_when_a_name_is_wrong(workspace):
    _, _, error = _run_command('activate', 'reviews', '--workspace', 'extensions-ws', '--workspace', 'typo-ws')
    assert error == "No workspace 'typo-ws'."

    _, _, error = _run_command('activate', 'not_deployed', '--workspace', 'extensions-ws')
    assert error == "No extension named 'not_deployed' is deployed."

    _, _, error = _run_command('deactivate', 'sign_in', '--workspace', 'extensions-ws')
    assert error == 'sign_in is always available and cannot be switched on or off.'

    assert not WorkspaceExtension.all_objects.filter(workspace=workspace).exists()


# ── Gating ───────────────────────────────────────────────────────────


class ReviewsView(APIView):
    permission_classes = [RequiresExtension]
    required_extension = 'reviews'

    def get(self, request):
        return Response({'ok': True})


class SignInView(ReviewsView):
    required_extension = 'sign_in'


class UnnamedView(APIView):
    permission_classes = [RequiresExtension]

    def get(self, request):
        return Response({'ok': True})


def _get(view_class, workspace=None):
    request = APIRequestFactory().get('/gated/')
    request.workspace = workspace
    return view_class.as_view()(request)


def test_a_view_of_a_switched_off_extension_says_so(workspace):
    response = _get(ReviewsView, workspace)

    assert response.status_code == 403
    assert response.data == {'code': 'extension_disabled', 'detail': 'reviews is not enabled for this workspace.'}


def test_a_view_of_an_active_extension_answers(workspace):
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)

    assert _get(ReviewsView, workspace).status_code == 200


def test_an_extension_that_is_always_available_needs_no_workspace(db):
    assert _get(SignInView).status_code == 200


def test_the_extension_can_come_from_the_views_app(workspace, monkeypatch):
    monkeypatch.setattr(
        extension_permissions.apps,
        'get_containing_app_config',
        lambda module: types.SimpleNamespace(label='reviews_app'),
    )

    assert _get(UnnamedView, workspace).data['code'] == 'extension_disabled'


def test_a_view_whose_app_ships_no_manifest_must_name_its_extension(workspace):
    with pytest.raises(ImproperlyConfigured):
        _get(UnnamedView, workspace)


def test_the_workspace_bound_while_authenticating_an_api_key_is_checked(workspace):
    class KeyAuthentication(BaseAuthentication):
        def authenticate(self, request):
            request._request.workspace = workspace
            return (User(username='api-key'), None)

    class KeyView(ReviewsView):
        authentication_classes = [KeyAuthentication]
        permission_classes = [IsAuthenticated, RequiresExtension]

    assert KeyView.as_view()(APIRequestFactory().get('/gated/')).data['code'] == 'extension_disabled'

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    services.invalidate(workspace.id)
    assert KeyView.as_view()(APIRequestFactory().get('/gated/')).status_code == 200


def test_an_anonymous_caller_is_asked_to_sign_in_before_hearing_about_the_extension(workspace):
    class SignedInView(ReviewsView):
        permission_classes = [IsAuthenticated, RequiresExtension]

    response = _get(SignedInView, workspace)

    assert response.status_code in (401, 403)
    assert 'code' not in response.data


def test_lists_can_keep_only_the_rows_of_workspaces_using_an_extension(workspace):
    paused = Workspace.objects.create(name='Paused', slug='paused-ws', is_active=True)
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    WorkspaceExtension.all_objects.create(workspace=paused, key='reviews', status=WorkspaceExtension.STATUS_PAUSED)
    WorkspaceExtension.all_objects.create(workspace=other, key='maps', status=WorkspaceExtension.STATUS_ACTIVE)

    assert list(Workspace.objects.filter(services.where_available('reviews', workspace_field=None))) == [workspace]
    rows = WorkspaceExtension.all_objects.filter(services.where_available('reviews'))
    assert sorted(rows.values_list('workspace__slug', 'key')) == [('extensions-ws', 'reviews')]
    assert (
        Workspace.objects.filter(services.where_available('sign_in', workspace_field=None)).count()
        == Workspace.objects.count()
    )
    assert not Workspace.objects.filter(services.where_available('not_deployed', workspace_field=None)).exists()


@pytest.mark.parametrize('key', ['brand_portal', 'maintenance'])
def test_the_command_retains_system_recovery_for_restricted_extensions(workspace, key):
    out, err, error = _run_command('activate', key, '--workspace', workspace.slug)

    assert (err, error) == ('', None)
    assert out.splitlines() == [f'{workspace.id} {workspace.slug}: {key} active']
    assert WorkspaceExtension.all_objects.get(workspace=workspace, key=key).status == 'active'


# ── Listeners and contributions ──────────────────────────────────────


def test_the_apps_of_extensions_a_workspace_does_not_use_are_listed(workspace):
    restricted = {'brand_portal_app', 'maintenance_app'}
    assert services.unavailable_apps(workspace) == {
        'reviews_app', 'insights_app', 'maps_app', *restricted,
    }

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    services.invalidate(workspace.id)

    # Review insights still waits for its own activation; sign-in and the importer are always available.
    assert services.unavailable_apps(workspace) == {'insights_app', 'maps_app', *restricted}
    assert services.unavailable_apps(None) == {
        'reviews_app', 'insights_app', 'maps_app', *restricted,
    }


@pytest.fixture
def dispatcher(monkeypatch):
    from bfg.core import events

    fresh = events.EventDispatcher()
    monkeypatch.setattr(events, 'global_dispatcher', fresh)
    return fresh


def test_a_listener_hears_only_the_workspaces_that_use_its_extension(workspace, dispatcher):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    heard = []
    listen_for('reviews', 'review.requested', heard.append)

    for each in (workspace, other):
        dispatcher.dispatch('review.requested', {'workspace': each, 'user': None, 'data': {}})
    # Some events carry the workspace in their data, as workspace.created does.
    dispatcher.dispatch('review.requested', {'data': {'workspace': other}})
    dispatcher.dispatch('review.requested', {'data': {'workspace': workspace}})

    assert heard == [
        {'workspace': workspace, 'user': None, 'data': {}},
        {'data': {'workspace': workspace}},
    ]


def test_a_workspace_extension_does_not_hear_events_without_a_workspace(dispatcher, caplog):
    caplog.set_level('WARNING', logger='bfg.common.extensions.events')
    reviews, sign_in = [], []
    listen_for('reviews', 'nightly.digest', reviews.append)
    listen_for('sign_in', 'nightly.digest', sign_in.append)

    for _ in range(2):
        dispatcher.dispatch('nightly.digest', {'data': {}})

    assert (reviews, len(sign_in)) == ([], 2)
    # Said once, so an emitter that leaves the workspace out can be found.
    skipped = [record.levelname for record in caplog.records if 'names no workspace' in record.getMessage()]
    assert skipped == ['WARNING']


def test_a_listener_can_say_where_its_events_keep_the_workspace(workspace, dispatcher):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    heard = []
    listen_for(
        'reviews', 'order.reviewable', heard.append,
        workspace_of=lambda event: event['data']['order'].workspace,
    )

    for each in (workspace, other):
        dispatcher.dispatch('order.reviewable', {'data': {'order': types.SimpleNamespace(workspace=each)}})

    assert [event['data']['order'].workspace for event in heard] == [workspace]


def test_a_listener_can_be_removed_by_the_callback_it_wraps(workspace, dispatcher):
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    heard = []

    def on_review_requested(event):
        heard.append(event)

    listen_for('reviews', 'review.requested', on_review_requested)
    dispatcher.remove_listener('review.requested', on_review_requested)
    dispatcher.dispatch('review.requested', {'workspace': workspace, 'data': {}})

    assert heard == []
    assert dispatcher.listeners['review.requested'] == []


def test_a_listener_waiting_on_an_undeclared_extension_never_runs_and_says_so(dispatcher, caplog):
    heard = []
    listen_for('reveiws', 'review.requested', heard.append)

    for _ in range(2):
        dispatcher.dispatch('review.requested', {'data': {}})

    assert heard == []
    assert [record.levelname for record in caplog.records if 'reveiws' in record.getMessage()] == ['ERROR']


def test_dashboard_stats_skip_apps_whose_extension_is_off(workspace, monkeypatch):
    from bfg.common import dashboard_extensions

    installed = []
    for name, label, stats in (
        ('reviews_pkg', 'reviews_app', {'reviews_to_write': 2}),
        ('points_pkg', 'points', {'points': 5}),
    ):
        module = types.ModuleType(f'{name}.dashboard_stats')
        module.get_me_dashboard_stats = lambda request, workspace, customer, stats=stats: stats
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
        monkeypatch.setitem(sys.modules, f'{name}.dashboard_stats', module)
        installed.append(types.SimpleNamespace(name=name, label=label))
    monkeypatch.setattr(dashboard_extensions, 'apps', types.SimpleNamespace(get_app_configs=lambda: installed))

    assert dashboard_extensions.collect_me_dashboard_stats(None, workspace, None) == {'points': 5}

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    services.invalidate(workspace.id)

    assert dashboard_extensions.collect_me_dashboard_stats(None, workspace, None) == {
        'points': 5, 'reviews_to_write': 2,
    }


def _request(view_class, workspace, data=None):
    factory = APIRequestFactory()
    request = factory.get('/') if data is None else factory.post('/', data, format='json')
    request.workspace = workspace
    force_authenticate(request, user=User(username='staff'))
    return view_class.as_view()(request)


def test_options_skip_apps_whose_extension_is_off(workspace, monkeypatch):
    from bfg.common import views as common_views

    installed = []
    for name, label in (('reviews_pkg', 'reviews_app'), ('points_pkg', 'points')):
        module = types.ModuleType(f'{name}.options')
        module.get_options = lambda workspace, name=name: {name: ['a']}
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
        monkeypatch.setitem(sys.modules, f'{name}.options', module)
        installed.append(types.SimpleNamespace(name=name, label=label))
    monkeypatch.setattr(common_views, 'apps', types.SimpleNamespace(get_app_configs=lambda: installed))

    assert _request(common_views.OptionsView, workspace).data == {'points_pkg': ['a']}

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    services.invalidate(workspace.id)

    assert _request(common_views.OptionsView, workspace).data == {'reviews_pkg': ['a'], 'points_pkg': ['a']}


@pytest.fixture
def capabilities(monkeypatch):
    from bfg.core.agent import AgentCapability, AgentCapabilityRegistry

    def handler(request, **arguments):
        return {'success': True}

    fake = {
        capability.id: capability
        for capability in (
            AgentCapability(
                id='reviews.summarise', name='Summarise reviews', description='',
                app_label='reviews_app', input_schema={}, handler=handler,
            ),
            AgentCapability(
                id='orders.count', name='Count orders', description='',
                app_label='shop', input_schema={}, handler=handler,
            ),
        )
    }
    monkeypatch.setattr(AgentCapabilityRegistry, '_capabilities', fake)
    return fake


def test_agents_are_offered_only_the_capabilities_a_workspace_can_use(workspace, capabilities):
    from bfg.core.agent_views import AgentCapabilitiesView

    def offered():
        return [capability['id'] for capability in _request(AgentCapabilitiesView, workspace).data['capabilities']]

    assert offered() == ['orders.count']

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    services.invalidate(workspace.id)

    assert offered() == ['reviews.summarise', 'orders.count']


def test_a_capability_of_a_switched_off_extension_is_not_executed(workspace, capabilities):
    from bfg.core.agent_views import AgentExecuteView

    def execute(capability_id):
        return _request(AgentExecuteView, workspace, {'capability_id': capability_id})

    refused = execute('reviews.summarise')
    assert refused.status_code == 403
    assert refused.data['code'] == 'extension_disabled'
    assert execute('orders.count').status_code == 200

    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    services.invalidate(workspace.id)

    assert execute('reviews.summarise').status_code == 200


def test_a_capability_must_name_an_installed_app(monkeypatch):
    from bfg.core.agent import AgentCapability, AgentCapabilityRegistry

    monkeypatch.setattr(AgentCapabilityRegistry, '_capabilities', {})
    stray = AgentCapability(
        id='stray.lookup', name='Stray lookup', description='', app_label='not_an_app',
        input_schema={}, handler=lambda request: {},
    )

    with pytest.raises(ValueError, match='not_an_app'):
        AgentCapabilityRegistry.register(stray)
    AgentCapabilityRegistry.register(replace(stray, app_label='shop'))
    assert AgentCapabilityRegistry.get('stray.lookup').app_label == 'shop'

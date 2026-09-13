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
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from bfg.common.extensions import registry, services
from bfg.common.extensions.manifest import (
    SCOPE_PLATFORM,
    SCOPE_TOOLING,
    SURFACE_ADMIN,
    SURFACE_STOREFRONT,
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


# ── Availability ─────────────────────────────────────────────────────


def test_platform_and_tooling_extensions_are_always_available(workspace):
    assert services.available_keys(workspace) == {'sign_in', 'importer'}
    assert services.is_available(workspace, 'sign_in')
    assert services.is_available(None, 'sign_in')
    assert not services.is_available(workspace, 'reviews')
    assert not services.is_available(workspace, 'not_deployed')


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


def test_staff_see_the_extensions_but_only_administrators_change_them(workspace):
    staff = _member(workspace, 'clerk', 'staff')
    admin = _member(workspace, 'owner', 'admin')

    listing = _client(workspace, staff).get('/api/v1/extensions/')
    assert listing.status_code == 200
    assert [row['key'] for row in listing.json()] == ['maps', 'review_insights', 'reviews']
    assert 'config' not in listing.json()[0]
    assert listing.json()[0]['unmet_prerequisites'] == ['MAPS_KEY is not configured.']
    assert _client(workspace, staff).post('/api/v1/extensions/reviews/activate/').status_code == 403

    response = _client(workspace, admin).post(
        '/api/v1/extensions/reviews/activate/', {'config': {'per_page': 5}}, format='json'
    )
    assert response.status_code == 200
    body = response.json()
    assert (body['status'], body['available'], body['config']) == ('active', True, {'per_page': 5})


def test_staff_of_another_workspace_are_refused(workspace):
    other = Workspace.objects.create(name='Other', slug='other-extensions-ws', is_active=True)
    outsider = _member(other, 'outsider', 'admin')

    assert _client(workspace, outsider).get('/api/v1/extensions/').status_code == 403
    assert _client(workspace, outsider).post('/api/v1/extensions/reviews/activate/').status_code == 403


def test_superusers_can_switch_extensions_in_any_workspace(workspace):
    root = User.objects.create_superuser(username='root', email='root@example.com', password='x')

    response = _client(workspace, root).post('/api/v1/extensions/reviews/activate/')

    assert (response.status_code, response.json()['status']) == (200, 'active')


def test_rejected_changes_say_why(workspace):
    api = _client(workspace, _member(workspace, 'owner', 'admin'))

    blocked = api.post('/api/v1/extensions/review_insights/activate/')
    assert blocked.status_code == 400
    assert blocked.json() == {'code': 'requires_inactive', 'detail': 'Activate reviews first.', 'requires': ['reviews']}

    assert api.post('/api/v1/extensions/not_deployed/activate/').status_code == 404

    too_many = api.patch('/api/v1/extensions/reviews/config/', {'config': {'per_page': 500}}, format='json')
    assert too_many.status_code == 400
    assert too_many.json()['code'] == 'invalid_config'

    saved = api.patch('/api/v1/extensions/reviews/config/', {'config': {'per_page': 30}}, format='json')
    assert saved.status_code == 200
    assert (saved.json()['status'], saved.json()['config']) == ('inactive', {'per_page': 30})


def test_a_broken_prerequisite_check_is_listed_as_unmet(workspace, monkeypatch, caplog):
    def lookup_fails(workspace):
        raise RuntimeError('lookup failed')

    broken = Prerequisite(code='broken', message='The lookup service is unreachable.', check=lookup_fails)
    monkeypatch.setitem(MANIFESTS, 'maps', replace(MANIFESTS['maps'], prerequisites=(broken,)))
    registry.reset_cache()

    listing = _client(workspace, _member(workspace, 'owner', 'admin')).get('/api/v1/extensions/')

    assert listing.status_code == 200
    maps = next(row for row in listing.json() if row['key'] == 'maps')
    assert maps['unmet_prerequisites'] == ['The lookup service is unreachable.']
    assert 'Prerequisite broken of extension maps failed' in caplog.text


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

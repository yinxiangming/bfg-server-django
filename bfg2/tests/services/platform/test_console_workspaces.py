"""
The console: workspaces and the extensions each one uses, for the people who run them.

``/api/v1/platform/console/workspaces/`` is shared by platform administrators, who reach
every workspace, ones they are not staff of included, and workspace owners, who reach
the ones they own. It sits on a public path, so no workspace is bound to its requests:
rows are gathered across workspaces, and the workspace an extension is looked at or
changed for is bound while its code runs.

Manifests are faked, as in ``test_workspace_extensions``.
"""

from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.pagination import PageNumberPagination
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from bfg.common.extensions import registry, services
from bfg.common.extensions.manifest import (
    ACTIVATION_PLATFORM_ADMIN,
    ACTIVATION_SYSTEM,
    SCOPE_PLATFORM,
    VISIBILITY_INTERNAL,
    VISIBILITY_PRIVATE,
    ExtensionManifest,
    Prerequisite,
)
from bfg.common.middleware import get_current_workspace, set_current_workspace
from bfg.common.models import AuditLog, StaffMember, StaffRole, Workspace, WorkspaceDomain, WorkspaceExtension
from bfg.platform.models.workspace_profile import WorkspacePlatformProfile
from bfg.platform.services.ownership import assign_workspace_owner
from bfg.platform.services.provision_service import suspend_workspace
from bfg.platform.views.console_views import ConsoleWorkspaceViewSet

User = get_user_model()
pytestmark = pytest.mark.django_db

CONSOLE = '/api/v1/platform/console/workspaces/'
DISPLAY_FIELDS = ('name', 'name_zh', 'description', 'description_zh', 'icon', 'admin_url')
NOT_FOUND = {'code': 'workspace_not_found', 'detail': 'Workspace not found.'}
BY_PLATFORM = {'id': None, 'username': None, 'by_platform': True}
HOOK_CALLS = []


def _clean_reviews_config(config):
    per_page = config.get('per_page', 10)
    if not isinstance(per_page, int) or not 1 <= per_page <= 50:
        raise ValueError('per_page must be a whole number from 1 to 50.')
    return {'per_page': per_page}


def _staff_usernames():
    # Through the tenant-scoped manager, as code written for a request bound to its
    # workspace reads staff: nothing comes back unless a workspace is bound.
    return sorted(StaffMember.objects.filter(is_active=True).values_list('user__username', flat=True))


MANIFESTS = {
    'reviews': ExtensionManifest(
        key='reviews',
        name='Reviews',
        name_zh='评价',
        description='Let shoppers review what they bought.',
        description_zh='让顾客评价买到的商品。',
        icon='tabler-star',
        admin_url='/admin/reviews',
        clean_config=_clean_reviews_config,
        on_activate=lambda workspace, record: HOOK_CALLS.append(('activate', workspace.id)),
        on_deactivate=lambda workspace, record: HOOK_CALLS.append(('deactivate', workspace.id)),
        app_label='reviews_app',
    ),
    'review_insights': ExtensionManifest(
        key='review_insights', name='Review insights', requires=('reviews',), app_label='insights_app',
    ),
    'maps': ExtensionManifest(
        key='maps',
        name='Maps',
        prerequisites=(
            Prerequisite(
                code='staff',
                message='Invite a member of staff first.',
                check=lambda workspace: bool(_staff_usernames()),
            ),
        ),
        app_label='maps_app',
    ),
    'sign_in': ExtensionManifest(key='sign_in', name='Sign-in', scope=SCOPE_PLATFORM, app_label='sign_in_app'),
    'brand_portal': ExtensionManifest(
        key='brand_portal',
        name='Brand portal',
        visibility=VISIBILITY_PRIVATE,
        activation_policy=ACTIVATION_PLATFORM_ADMIN,
        clean_config=lambda config: {'brand': str(config.get('brand', '')).strip()},
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
    cache.clear()
    HOOK_CALLS.clear()
    yield
    registry.reset_cache()
    cache.clear()


@pytest.fixture(autouse=True)
def platform_workspace(settings, db):
    """Embedded mode with a real management workspace, so a refusal below is about
    who the caller is rather than a missing platform workspace."""
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = 'platform'
    return Workspace.objects.create(name='Platform', slug='platform', is_active=True)


def _user(username):
    return User.objects.create_user(username=username, email=f'{username}@example.com', password='x')


def join(workspace, user, role_code, is_active=True):
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code=role_code, defaults={'name': role_code})
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=is_active)
    return user


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def detail_url(workspace_id):
    return f'{CONSOLE}{workspace_id}/'


def extension_url(workspace_id, key, action):
    return f'{CONSOLE}{workspace_id}/extensions/{key}/{action}/'


def rows(response):
    data = response.data
    return data['results'] if isinstance(data, dict) else data


def summary(user):
    return {'id': user.id, 'username': user.username, 'email': user.email}


@pytest.fixture
def operator(platform_workspace):
    return User.objects.create_superuser(
        username='operator', email='operator@example.com', password='x',
    )


@pytest.fixture
def shop():
    """A workspace the operator is not staff of, with an owner, staff and three domains."""
    workspace = Workspace.objects.create(name='Harbour Books', slug='harbour-books', is_active=True)
    assign_workspace_owner(workspace, _user('harbour-owner'))
    join(workspace, _user('harbour-admin'), 'admin')
    join(workspace, _user('harbour-clerk'), 'staff')
    join(workspace, _user('harbour-leaver'), 'staff', is_active=False)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname='harbour-books.shops.test',
        kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
    )
    WorkspaceDomain.objects.create(workspace=workspace, hostname='books.harbour.test', kind=WorkspaceDomain.KIND_CUSTOM)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname='harbourbooks.test',
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        is_primary=True,
    )
    return workspace


@pytest.fixture
def shop_admin(shop):
    return User.objects.get(username='harbour-admin')


@pytest.fixture
def shop_owner(shop):
    return User.objects.get(username='harbour-owner')


def _furnish(name):
    """A workspace with something in every column of its row."""
    workspace = Workspace.objects.create(name=f'{name.title()} Shop', slug=f'{name}-shop', is_active=True)
    assign_workspace_owner(workspace, _user(f'{name}-owner'))
    join(workspace, _user(f'{name}-clerk'), 'staff')
    WorkspaceDomain.objects.create(workspace=workspace, hostname=f'{name}.shop.test', kind=WorkspaceDomain.KIND_CUSTOM)
    WorkspaceExtension.all_objects.create(workspace=workspace, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE)
    return workspace


# ── Who may use it ───────────────────────────────────────────────────


def _every_endpoint(client, workspace):
    return [
        client.get(CONSOLE),
        client.get(detail_url(workspace.id)),
        client.post(extension_url(workspace.id, 'reviews', 'activate'), {}, format='json'),
        client.post(extension_url(workspace.id, 'reviews', 'deactivate'), {}, format='json'),
        client.patch(extension_url(workspace.id, 'reviews', 'config'), {'config': {'per_page': 5}}, format='json'),
    ]


def test_anonymous_callers_are_refused(shop):
    statuses = [response.status_code for response in _every_endpoint(client_for(), shop)]

    assert all(code in (401, 403) for code in statuses), statuses
    assert not WorkspaceExtension.all_objects.exists()


@pytest.mark.parametrize(
    'membership', ['admin of the workspace', 'staff of another workspace', 'staff of the platform workspace']
)
def test_accounts_that_neither_administer_the_platform_nor_own_a_workspace_are_refused(
    shop, platform_workspace, membership
):
    elsewhere = Workspace.objects.create(name='Elsewhere', slug='elsewhere', is_active=True)
    workspace, role_code = {
        'admin of the workspace': (shop, 'admin'),
        'staff of another workspace': (elsewhere, 'staff'),
        'staff of the platform workspace': (platform_workspace, 'staff'),
    }[membership]
    caller = join(workspace, _user('caller'), role_code)

    statuses = [response.status_code for response in _every_endpoint(client_for(caller), shop)]

    assert statuses == [403] * 5
    assert not WorkspaceExtension.all_objects.exists()


def test_a_platform_administrator_is_let_in(operator, shop):
    client = client_for(operator)

    assert client.get(CONSOLE).status_code == 200
    assert client.get(detail_url(shop.id)).status_code == 200


def test_restricted_extensions_are_disclosed_only_to_their_management_audience(
    operator, shop, shop_owner
):
    keys_for = lambda user: {
        row['key'] for row in client_for(user).get(detail_url(shop.id)).data['extensions']
    }

    assert keys_for(shop_owner) == {'maps', 'review_insights', 'reviews'}
    assert keys_for(operator) == {'brand_portal', 'maps', 'review_insights', 'reviews'}


# ── The list ─────────────────────────────────────────────────────────


def test_the_list_shows_every_workspace_whoever_its_staff_are(operator, shop):
    for key, status in (
        ('reviews', WorkspaceExtension.STATUS_ACTIVE),
        ('review_insights', WorkspaceExtension.STATUS_ACTIVE),
        ('maps', WorkspaceExtension.STATUS_INACTIVE),
        # Left behind by an extension this deployment no longer ships.
        ('retired', WorkspaceExtension.STATUS_ACTIVE),
    ):
        WorkspaceExtension.all_objects.create(workspace=shop, key=key, status=status)
    Workspace.objects.create(name='Closed', slug='closed', is_active=False)
    suspended = Workspace.objects.create(name='Suspended', slug='suspended', is_active=True)
    WorkspacePlatformProfile.objects.create(workspace=suspended)
    suspend_workspace(suspended)

    response = client_for(operator).get(CONSOLE)

    assert response.status_code == 200
    listed = rows(response)
    assert [row['slug'] for row in listed] == ['suspended', 'closed', 'harbour-books', 'platform']
    by_slug = {row['slug']: row for row in listed}
    assert by_slug['harbour-books'] == {
        'id': shop.id,
        'name': 'Harbour Books',
        'slug': 'harbour-books',
        'is_active': True,
        'is_platform': False,
        'suspended_at': None,
        'created_at': shop.created_at,
        'domains': ['harbourbooks.test', 'books.harbour.test', 'harbour-books.shops.test'],
        'owner': summary(User.objects.get(username='harbour-owner')),
        'owned_by_viewer': False,
        'staff_count': 2,
        'active_extensions': ['review_insights', 'reviews'],
    }
    # A Django superuser does not need a tenant StaffMember row to operate the
    # control plane, so it is intentionally not counted as platform workspace staff.
    assert (by_slug['platform']['is_platform'], by_slug['platform']['staff_count']) == (True, 0)
    assert (by_slug['closed']['is_active'], by_slug['closed']['owner'], by_slug['closed']['domains']) == (
        False, None, [],
    )
    assert by_slug['suspended']['is_active'] is False
    assert by_slug['suspended']['suspended_at'] is not None


def test_search_matches_the_name_or_the_slug_in_any_case(operator, shop):
    Workspace.objects.create(name='Tidewater Goods', slug='tw-market', is_active=True)
    client = client_for(operator)

    def found(term):
        return sorted(row['slug'] for row in rows(client.get(CONSOLE, {'search': term})))

    assert found('HARBOUR') == ['harbour-books']
    assert found('goods') == ['tw-market']
    assert found('market') == ['tw-market']
    assert found('nowhere') == []
    assert found('') == ['harbour-books', 'platform', 'tw-market']


def test_the_list_takes_as_many_queries_for_many_workspaces_as_for_one(operator):
    client = client_for(operator)

    def list_workspaces():
        with CaptureQueriesContext(connection) as queries:
            response = client.get(CONSOLE)
        assert response.status_code == 200
        return len(rows(response)), len(queries.captured_queries)

    _furnish('first')
    listed_few, queries_for_few = list_workspaces()
    for name in ('second', 'third', 'fourth'):
        _furnish(name)
    listed_many, queries_for_many = list_workspaces()

    assert (listed_few, listed_many) == (2, 5)
    assert queries_for_many == queries_for_few


def test_a_paginated_list_fills_in_the_rows_of_its_page(operator, monkeypatch):
    class TwoPerPage(PageNumberPagination):
        page_size = 2

    # DRF reads DEFAULT_PAGINATION_CLASS into the view class once, and these settings set none.
    monkeypatch.setattr(ConsoleWorkspaceViewSet, 'pagination_class', TwoPerPage)
    for name in ('first', 'second', 'third'):
        _furnish(name)

    body = client_for(operator).get(CONSOLE, {'search': 'shop', 'page': 2}).data

    assert body['count'] == 3
    assert [(row['slug'], row['owner']['username'], row['active_extensions']) for row in body['results']] == [
        ('first-shop', 'first-owner', ['reviews']),
    ]


# ── One workspace ────────────────────────────────────────────────────


def test_the_detail_adds_every_extension_with_its_configuration(
    operator, shop, shop_admin, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.activate(shop, 'reviews', user=shop_admin, config={'per_page': 5})
    client = client_for(operator)

    body = client.get(detail_url(shop.id)).data

    listed = next(row for row in rows(client.get(CONSOLE)) if row['id'] == shop.id)
    assert {field: value for field, value in body.items() if field != 'extensions'} == listed
    extensions = {row['key']: row for row in body['extensions']}
    assert list(extensions) == ['brand_portal', 'maps', 'review_insights', 'reviews']
    reviews = extensions['reviews']
    assert {field: reviews[field] for field in DISPLAY_FIELDS} == {
        'name': 'Reviews',
        'name_zh': '评价',
        'description': 'Let shoppers review what they bought.',
        'description_zh': '让顾客评价买到的商品。',
        'icon': 'tabler-star',
        'admin_url': '/admin/reviews',
    }
    assert (reviews['status'], reviews['available'], reviews['config']) == ('active', True, {'per_page': 5})
    assert reviews['status_changed_by'] == summary(shop_admin)
    assert reviews['activated_at'] is not None
    assert (extensions['review_insights']['config'], extensions['review_insights']['status_changed_by']) == ({}, None)
    # The prerequisite reads staff through the tenant-scoped manager, which finds the
    # workspace's staff only because the workspace is bound while it is checked.
    assert extensions['maps']['unmet_prerequisites'] == []


def test_a_broken_prerequisite_check_is_listed_as_unmet(operator, shop, monkeypatch, caplog):
    def lookup_fails(workspace):
        raise RuntimeError('lookup failed')

    broken = Prerequisite(code='broken', message='The lookup service is unreachable.', check=lookup_fails)
    monkeypatch.setitem(MANIFESTS, 'maps', replace(MANIFESTS['maps'], prerequisites=(broken,)))
    registry.reset_cache()

    response = client_for(operator).get(detail_url(shop.id))

    assert response.status_code == 200
    maps = next(row for row in response.data['extensions'] if row['key'] == 'maps')
    assert maps['unmet_prerequisites'] == ['The lookup service is unreachable.']
    assert 'Prerequisite broken of extension maps failed' in caplog.text


def test_a_workspace_that_does_not_exist_is_not_found(operator):
    client = client_for(operator)
    missing = Workspace.objects.order_by('-id').first().id + 1

    responses = [
        client.get(detail_url(missing)),
        client.post(extension_url(missing, 'reviews', 'activate'), {}, format='json'),
        client.post(extension_url(missing, 'reviews', 'deactivate'), {}, format='json'),
        client.patch(extension_url(missing, 'reviews', 'config'), {'config': {}}, format='json'),
    ]

    assert [(response.status_code, response.json()) for response in responses] == [(404, NOT_FOUND)] * 4
    assert not WorkspaceExtension.all_objects.exists()


# ── Managing another workspace's extensions ──────────────────────────


def test_a_platform_administrator_switches_extensions_for_a_workspace_they_are_not_staff_of(
    operator, platform_workspace, shop, django_capture_on_commit_callbacks
):
    client = client_for(operator)

    with django_capture_on_commit_callbacks(execute=True):
        activated = client.post(
            extension_url(shop.id, 'reviews', 'activate'), {'config': {'per_page': 5}}, format='json'
        )
    assert activated.status_code == 200, activated.data
    body = activated.json()
    assert (body['status'], body['available'], body['config']) == ('active', True, {'per_page': 5})
    assert body['status_changed_by'] == summary(operator)
    assert 'reviews' in services.available_keys(shop)

    with django_capture_on_commit_callbacks(execute=True):
        configured = client.patch(
            extension_url(shop.id, 'reviews', 'config'), {'config': {'per_page': 30}}, format='json'
        )
    assert configured.status_code == 200
    assert (configured.json()['config'], configured.json()['status_changed_by']) == (
        {'per_page': 30}, summary(operator),
    )

    with django_capture_on_commit_callbacks(execute=True):
        deactivated = client.post(extension_url(shop.id, 'reviews', 'deactivate'), {}, format='json')
    assert deactivated.status_code == 200
    body = deactivated.json()
    assert (body['status'], body['available'], body['status_changed_by']) == ('inactive', False, summary(operator))
    assert 'reviews' not in services.available_keys(shop)

    assert HOOK_CALLS == [('activate', shop.id), ('deactivate', shop.id)]
    assert not WorkspaceExtension.all_objects.filter(workspace=platform_workspace).exists()


def test_a_platform_administrator_manages_a_private_extension_and_actions_are_audited(
    operator, shop
):
    client = client_for(operator)

    activated = client.post(
        extension_url(shop.id, 'brand_portal', 'activate'),
        {'config': {'brand': ' Surlex ', 'secret': 'must-not-be-audited'}},
        format='json',
    )
    configured = client.patch(
        extension_url(shop.id, 'brand_portal', 'config'),
        {'config': {'brand': 'Idlevo', 'secret': 'must-not-be-audited'}},
        format='json',
    )

    assert activated.status_code == 200
    assert activated.data['visibility'] == VISIBILITY_PRIVATE
    assert activated.data['activation_policy'] == ACTIVATION_PLATFORM_ADMIN
    assert configured.status_code == 200
    assert configured.data['config'] == {'brand': 'Idlevo'}
    audits = list(
        AuditLog.objects.filter(workspace=shop, user=operator).order_by('created_at')
    )
    assert [entry.description for entry in audits] == [
        'Activated extension brand_portal.',
        'Updated configuration for extension brand_portal.',
    ]
    assert [entry.changes for entry in audits] == [
        {
            'status': {'old': WorkspaceExtension.STATUS_INACTIVE, 'new': WorkspaceExtension.STATUS_ACTIVE},
            'config': {'changed': True},
        },
        {'config': {'changed': True}},
    ]
    assert 'must-not-be-audited' not in str([entry.changes for entry in audits])


def test_refused_changes_say_why(operator, shop):
    client = client_for(operator)

    answers = [
        client.post(extension_url(shop.id, 'review_insights', 'activate'), {}, format='json'),
        client.post(extension_url(shop.id, 'not_deployed', 'activate'), {}, format='json'),
        client.patch(extension_url(shop.id, 'reviews', 'config'), {'config': {'per_page': 500}}, format='json'),
        client.patch(extension_url(shop.id, 'reviews', 'config'), {}, format='json'),
    ]

    assert [(response.status_code, response.json()) for response in answers] == [
        (400, {'code': 'requires_inactive', 'detail': 'Activate reviews first.', 'requires': ['reviews']}),
        (404, {'code': 'unknown_extension', 'detail': "No extension named 'not_deployed' is deployed."}),
        (400, {'code': 'invalid_config', 'detail': 'per_page must be a whole number from 1 to 50.'}),
        (400, {'code': 'invalid_config', 'detail': 'Send the configuration as {"config": {...}}.'}),
    ]
    assert not WorkspaceExtension.all_objects.exists()


# ── Owners ───────────────────────────────────────────────────────────


def test_an_owner_reaches_only_the_workspaces_they_own(shop, shop_owner):
    annex = Workspace.objects.create(name='Harbour Annex', slug='harbour-annex', is_active=False)
    assign_workspace_owner(annex, shop_owner)
    _furnish('rival')
    client = client_for(shop_owner)

    listed = rows(client.get(CONSOLE))

    # Owning is enough: the owner is on the staff of neither workspace.
    assert [(row['slug'], row['owned_by_viewer']) for row in listed] == [
        ('harbour-annex', True),
        ('harbour-books', True),
    ]
    assert [row['slug'] for row in rows(client.get(CONSOLE, {'search': 'annex'}))] == ['harbour-annex']
    assert rows(client.get(CONSOLE, {'search': 'rival'})) == []
    detail = client.get(detail_url(shop.id))
    assert (detail.status_code, detail.data['owned_by_viewer']) == (200, True)


def test_an_owner_switches_extensions_for_a_workspace_they_own(shop, shop_owner, django_capture_on_commit_callbacks):
    client = client_for(shop_owner)

    with django_capture_on_commit_callbacks(execute=True):
        activated = client.post(extension_url(shop.id, 'reviews', 'activate'), {}, format='json')
    with django_capture_on_commit_callbacks(execute=True):
        configured = client.patch(
            extension_url(shop.id, 'reviews', 'config'), {'config': {'per_page': 20}}, format='json'
        )
    with django_capture_on_commit_callbacks(execute=True):
        deactivated = client.post(extension_url(shop.id, 'reviews', 'deactivate'), {}, format='json')

    # The owner belongs to the workspace, so they are named in their own answers, without an email.
    by_owner = {'id': shop_owner.id, 'username': 'harbour-owner'}
    assert [response.status_code for response in (activated, configured, deactivated)] == [200, 200, 200]
    assert (activated.json()['status'], activated.json()['status_changed_by']) == ('active', by_owner)
    assert (configured.json()['config'], configured.json()['status_changed_by']) == ({'per_page': 20}, by_owner)
    assert (deactivated.json()['status'], deactivated.json()['status_changed_by']) == ('inactive', by_owner)
    assert HOOK_CALLS == [('activate', shop.id), ('deactivate', shop.id)]
    assert 'reviews' not in services.available_keys(shop)


def test_an_owner_cannot_probe_or_change_a_private_extension(shop, shop_owner):
    client = client_for(shop_owner)
    requests = [
        client.post(extension_url(shop.id, 'brand_portal', 'activate'), {}, format='json'),
        client.post(extension_url(shop.id, 'brand_portal', 'deactivate'), {}, format='json'),
        client.patch(
            extension_url(shop.id, 'brand_portal', 'config'),
            {'config': {'brand': 'Surlex'}},
            format='json',
        ),
        client.post(extension_url(shop.id, 'brand_portal', 'restore'), {}, format='json'),
        client.post(extension_url(shop.id, 'brand_portal', 'acquire'), {}, format='json'),
    ]

    assert [(response.status_code, response.data['code']) for response in requests] == [
        (404, 'unknown_extension'),
    ] * 5
    assert not WorkspaceExtension.all_objects.filter(workspace=shop, key='brand_portal').exists()
    assert not AuditLog.objects.filter(workspace=shop).exists()


def test_an_owner_is_not_told_whether_a_workspace_they_do_not_own_exists(shop, shop_owner):
    rival = _furnish('rival')
    missing = Workspace.objects.order_by('-id').first().id + 1
    client = client_for(shop_owner)

    def answers(workspace_id):
        return [
            (response.status_code, response.json())
            for response in (
                client.get(detail_url(workspace_id)),
                client.post(extension_url(workspace_id, 'reviews', 'activate'), {}, format='json'),
                client.post(extension_url(workspace_id, 'reviews', 'deactivate'), {}, format='json'),
                client.patch(extension_url(workspace_id, 'reviews', 'config'), {'config': {}}, format='json'),
            )
        ]

    refused = answers(rival.id)

    assert refused == [(404, NOT_FOUND)] * 4
    assert refused == answers(missing)
    rival_reviews = WorkspaceExtension.all_objects.get(workspace=rival, key='reviews')
    assert (rival_reviews.status, rival_reviews.config) == (WorkspaceExtension.STATUS_ACTIVE, {})


def test_owners_are_not_told_which_platform_administrator_switched_an_extension(
    operator, shop, shop_admin, shop_owner
):
    activated = client_for(operator).post(extension_url(shop.id, 'reviews', 'activate'), {}, format='json')
    assert activated.status_code == 200
    services.activate(shop, 'review_insights', user=shop_admin)

    def changers_seen_by(user):
        response = client_for(user).get(detail_url(shop.id))
        assert response.status_code == 200
        return response, {row['key']: row['status_changed_by'] for row in response.data['extensions']}

    for_owner, seen_by_owner = changers_seen_by(shop_owner)
    assert seen_by_owner == {
        'maps': None,
        'review_insights': {'id': shop_admin.id, 'username': 'harbour-admin'},
        'reviews': BY_PLATFORM,
    }
    assert operator.email.encode() not in for_owner.content
    assert shop_admin.email.encode() not in for_owner.content

    _, seen_by_operator = changers_seen_by(operator)
    assert seen_by_operator == {
        'brand_portal': None,
        'maps': None,
        'review_insights': summary(shop_admin),
        'reviews': summary(operator),
    }


def test_changers_are_looked_up_in_as_many_queries_for_many_extensions_as_for_one(
    operator, shop, shop_admin, shop_owner
):
    clerk = User.objects.get(username='harbour-clerk')
    client = client_for(shop_owner)

    def queries_for_detail():
        with CaptureQueriesContext(connection) as queries:
            assert client.get(detail_url(shop.id)).status_code == 200
        return len(queries.captured_queries)

    # A changer from outside the workspace, so the owner is looked up as well as the staff.
    WorkspaceExtension.all_objects.create(workspace=shop, key='reviews', status_changed_by=operator)
    for_one = queries_for_detail()
    WorkspaceExtension.all_objects.create(workspace=shop, key='review_insights', status_changed_by=shop_admin)
    WorkspaceExtension.all_objects.create(workspace=shop, key='maps', status_changed_by=clerk)
    for_three = queries_for_detail()

    assert for_three == for_one


def _close(workspace, closure):
    if closure == 'suspended':
        # As suspending leaves a workspace: inactive, with the time it was suspended on its profile.
        suspend_workspace(Workspace.objects.get(pk=workspace.pk))
    else:
        Workspace.objects.filter(pk=workspace.pk).update(is_active=False)


@pytest.mark.parametrize('closure', ['suspended', 'inactive'])
def test_an_owner_only_reads_a_workspace_that_is_suspended_or_inactive(shop, shop_owner, closure):
    WorkspaceExtension.all_objects.create(
        workspace=shop, key='reviews', status=WorkspaceExtension.STATUS_ACTIVE, config={'per_page': 5}
    )
    _close(shop, closure)
    client = client_for(shop_owner)

    refused = [
        client.post(extension_url(shop.id, 'review_insights', 'activate'), {}, format='json'),
        client.post(extension_url(shop.id, 'reviews', 'deactivate'), {}, format='json'),
        client.patch(extension_url(shop.id, 'reviews', 'config'), {'config': {'per_page': 30}}, format='json'),
    ]

    assert [(response.status_code, response.json()['code']) for response in refused] == [
        (403, f'workspace_{closure}'),
    ] * 3
    assert set(refused[0].json()) == {'code', 'detail'}
    reviews = WorkspaceExtension.all_objects.get(workspace=shop, key='reviews')
    assert (reviews.status, reviews.config) == (WorkspaceExtension.STATUS_ACTIVE, {'per_page': 5})
    assert not WorkspaceExtension.all_objects.filter(workspace=shop, key='review_insights').exists()
    assert HOOK_CALLS == []
    # Looking is still allowed.
    assert [row['slug'] for row in rows(client.get(CONSOLE))] == ['harbour-books']
    assert client.get(detail_url(shop.id)).status_code == 200


def test_a_platform_administrator_still_changes_a_suspended_workspace(operator, shop):
    _close(shop, 'suspended')

    response = client_for(operator).post(extension_url(shop.id, 'reviews', 'activate'), {}, format='json')

    assert (response.status_code, response.json()['status']) == (200, 'active')


def test_a_platform_administrator_who_owns_a_workspace_is_told_which_one(operator, shop):
    theirs = Workspace.objects.create(name='Night Market', slug='night-market', is_active=True)
    assign_workspace_owner(theirs, operator)
    client = client_for(operator)

    listed = rows(client.get(CONSOLE))

    assert {row['slug']: row['owned_by_viewer'] for row in listed} == {
        'night-market': True,
        'harbour-books': False,
        'platform': False,
    }
    assert client.get(detail_url(theirs.id)).data['owned_by_viewer'] is True
    assert client.get(detail_url(shop.id)).data['owned_by_viewer'] is False


# ── Binding the workspace a change is for ────────────────────────────


def _record_binding(event):
    def hook(workspace, record):
        HOOK_CALLS.append((event, get_current_workspace(), _staff_usernames()))

    return hook


def test_hooks_read_the_workspace_they_run_for_through_tenant_scoped_managers(operator, shop, monkeypatch):
    monkeypatch.setitem(
        MANIFESTS,
        'reviews',
        replace(
            MANIFESTS['reviews'],
            on_activate=_record_binding('activate'),
            on_deactivate=_record_binding('deactivate'),
        ),
    )
    registry.reset_cache()
    client = client_for(operator)

    assert client.post(extension_url(shop.id, 'reviews', 'activate'), {}, format='json').status_code == 200
    assert client.post(extension_url(shop.id, 'reviews', 'deactivate'), {}, format='json').status_code == 200

    # The shop's staff, not those of the platform workspace the operator belongs to.
    assert HOOK_CALLS == [
        ('activate', shop, ['harbour-admin', 'harbour-clerk']),
        ('deactivate', shop, ['harbour-admin', 'harbour-clerk']),
    ]
    assert get_current_workspace() is None


def _call_view(action, workspace, key, user):
    request = APIRequestFactory().post(extension_url(workspace.id, key, action), {}, format='json')
    force_authenticate(request, user=user)
    return ConsoleWorkspaceViewSet.as_view({'post': action})(request, pk=str(workspace.id), key=key)


def test_the_binding_from_before_a_change_is_put_back_even_when_a_hook_fails(
    operator, platform_workspace, shop, monkeypatch
):
    def refuse(workspace, record):
        raise RuntimeError('cleanup failed')

    monkeypatch.setitem(MANIFESTS, 'reviews', replace(MANIFESTS['reviews'], on_deactivate=refuse))
    registry.reset_cache()
    # The view is called without the middleware, which clears the binding on its own.
    set_current_workspace(platform_workspace)

    assert _call_view('activate_extension', shop, 'reviews', operator).status_code == 200
    assert get_current_workspace() == platform_workspace

    with pytest.raises(RuntimeError):
        _call_view('deactivate_extension', shop, 'reviews', operator)
    assert get_current_workspace() == platform_workspace
    assert WorkspaceExtension.all_objects.get(workspace=shop, key='reviews').status == WorkspaceExtension.STATUS_ACTIVE

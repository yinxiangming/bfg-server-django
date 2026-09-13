"""
Creating a workspace through ``POST /api/v1/platform/workspaces/``.

Only an account that already owns a workspace or administers one may create
another, and it may own ``BFG_MAX_OWNED_WORKSPACES_PER_USER`` of them at most,
suspended and inactive ones included. ``me/`` reports which of the two stands in
the way, by the same rule the create request applies.

Embedded, the request provisions the workspace itself, in one transaction, and
queues nothing: the workspace comes back with its settings, currency, store,
notification templates, owner and platform records, and a broker that is down
changes none of that.
"""
import re
from functools import partial
from types import SimpleNamespace

import pytest
from celery.app.task import Task
from django.contrib.auth import get_user_model
from django.db.models.query import QuerySet
from kombu.exceptions import OperationalError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from bfg.common.models import Settings, StaffMember, StaffRole, Workspace
from bfg.core.events import after_commit, global_dispatcher
from bfg.core.tasks import deliver_ga4_events
from bfg.finance.models import Currency
from bfg.inbox.models import MessageTemplate
from bfg.inbox.notification_templates import NOTIFICATION_CODES
from bfg.platform.models import PlatformMembership, WorkspaceOperation, WorkspacePlatformProfile
from bfg.platform.services import workspace_creation
from bfg.platform.services.ownership import assign_workspace_owner
from bfg.platform.services.provision_service import suspend_workspace
from bfg.shop.models import Store

User = get_user_model()
pytestmark = pytest.mark.django_db

WORKSPACES_URL = '/api/v1/platform/workspaces/'
ME_URL = '/api/v1/platform/workspaces/me/'

# Every workspace in ``me/`` carries exactly these, and so does a created one.
ME_WORKSPACE_FIELDS = {
    'id', 'name', 'slug', 'created_at', 'domain', 'status', 'suspended_at',
    'role', 'is_member', 'is_owner', 'plan', 'credits', 'extensions',
}


@pytest.fixture(autouse=True)
def platform_workspace(settings, db):
    """Embedded mode with a real management workspace."""
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = 'platform'
    return Workspace.objects.create(name='Platform', slug='platform', is_active=True)


@pytest.fixture
def queued(monkeypatch):
    """``provision_workspace.delay`` calls, captured where creating a workspace looks the task up.

    Only where a test asks for it: everywhere else a publish goes through Celery,
    which is how the broker-down test sees every publish a create makes.
    """
    calls = []
    monkeypatch.setattr(
        workspace_creation, 'provision_workspace', SimpleNamespace(delay=lambda **kwargs: calls.append(kwargs)),
    )
    return calls


def make_user(username):
    return User.objects.create_user(username=username, password='x')


def make_workspace(slug, **fields):
    return Workspace.objects.create(name=slug.title(), slug=slug, **fields)


def join(workspace, user, role_code, is_active=True):
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code=role_code, defaults={'name': role_code})
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=is_active)


def admin_elsewhere(username):
    """An account that may create workspaces: the admin of one it does not own."""
    user = make_user(username)
    join(make_workspace(f'{username}-shop'), user, 'admin')
    return user


def client_for(user, workspace=None):
    """A client authenticated with an access token, for *workspace* when one is given."""
    token = AccessToken.for_user(user)
    if workspace is not None:
        token['workspace_id'] = workspace.id
    client = APIClient()
    client.force_authenticate(user=user, token=token)
    return client


def create(user, body, workspace=None):
    return client_for(user, workspace).post(WORKSPACES_URL, body, format='json')


def get_me(user):
    response = client_for(user).get(ME_URL)
    assert response.status_code == 200, response.data
    return response.json()


def locale_of(workspace_id):
    settings_obj = Settings.objects.get(workspace_id=workspace_id)
    return settings_obj.country, settings_obj.default_currency, settings_obj.default_language


class TestWhoMayCreate:
    @pytest.mark.parametrize('standing', ['none', 'staff-not-admin', 'admin-no-longer', 'owner-no-longer'])
    def test_an_account_that_neither_owns_nor_administers_a_workspace_is_refused(self, standing):
        user = make_user('newcomer')
        shop = make_workspace('shop')
        if standing == 'staff-not-admin':
            join(shop, user, 'customer_service')
        elif standing == 'admin-no-longer':
            join(shop, user, 'admin', is_active=False)
        elif standing == 'owner-no-longer':
            assign_workspace_owner(shop, user)
            PlatformMembership.objects.filter(user=user).update(is_active=False)
        workspaces_before = Workspace.objects.count()

        # Refused before the body is looked at: this one has no name.
        response = create(user, {'slug': 'refused'})

        assert response.status_code == 403
        body = response.json()
        assert set(body) == {'detail', 'code'}
        assert body['code'] == 'workspace_create_forbidden'
        assert Workspace.objects.count() == workspaces_before

    @pytest.mark.parametrize('standing', ['admin-elsewhere', 'admin-of-suspended', 'owner', 'owner-of-suspended'])
    def test_the_owner_or_an_admin_of_any_workspace_may_create_one(self, standing):
        user = make_user('founder')
        shop = make_workspace('shop')
        if standing.startswith('admin'):
            join(shop, user, 'admin')
        else:
            assign_workspace_owner(shop, user)
        if standing.endswith('suspended'):
            suspend_workspace(shop)

        response = create(user, {'name': 'Second Shop'})

        assert response.status_code == 201, response.data
        owner = PlatformMembership.objects.get(profile__workspace__slug='second-shop')
        assert (owner.user, owner.role, owner.is_active) == (user, 'owner', True)


class TestLimit:
    def test_the_fourth_workspace_is_refused_with_the_limit(self):
        user = admin_elsewhere('founder')
        for number in range(3):
            response = create(user, {'name': f'Shop {number}'})
            assert response.status_code == 201, response.data

        response = create(user, {'name': 'Shop 3'})

        assert response.status_code == 400
        body = response.json()
        assert set(body) == {'detail', 'code', 'limit'}
        assert (body['code'], body['limit']) == ('workspace_limit_reached', 3)
        assert not Workspace.objects.filter(slug='shop-3').exists()
        assert PlatformMembership.objects.filter(user=user, role='owner', is_active=True).count() == 3

    def test_suspended_and_inactive_workspaces_count_towards_it(self, settings):
        settings.BFG_MAX_OWNED_WORKSPACES_PER_USER = 2
        user = make_user('founder')
        suspended = make_workspace('suspended')
        assign_workspace_owner(suspended, user)
        suspend_workspace(suspended)
        assign_workspace_owner(make_workspace('dormant', is_active=False), user)

        response = create(user, {'name': 'Third'})

        assert response.status_code == 400
        assert (response.json()['code'], response.json()['limit']) == ('workspace_limit_reached', 2)
        assert not Workspace.objects.filter(slug='third').exists()

    def test_an_ownership_that_has_ended_does_not_count(self, settings):
        settings.BFG_MAX_OWNED_WORKSPACES_PER_USER = 1
        user = admin_elsewhere('founder')
        former = make_workspace('former')
        assign_workspace_owner(former, user)
        PlatformMembership.objects.filter(user=user, profile__workspace=former).update(is_active=False)

        response = create(user, {'name': 'Fresh'})

        assert response.status_code == 201, response.data


class TestAskedAgainWithTheAccountLocked:
    """``create_owned_workspace`` applies both rules itself once it holds the account's
    row, so an answer that has gone stale since the request began does not decide."""

    @pytest.fixture(autouse=True)
    def stale_first_answer(self, monkeypatch):
        from bfg.platform.views import workspace_views

        monkeypatch.setattr(workspace_views, 'ensure_workspace_create_allowed', lambda user: None)

    def test_the_limit(self, settings):
        settings.BFG_MAX_OWNED_WORKSPACES_PER_USER = 1
        user = make_user('founder')
        assign_workspace_owner(make_workspace('first'), user)

        response = create(user, {'name': 'Second'})

        assert response.status_code == 400
        body = response.json()
        assert set(body) == {'detail', 'code', 'limit'}
        assert (body['code'], body['limit']) == ('workspace_limit_reached', 1)
        assert not Workspace.objects.filter(slug='second').exists()

    def test_the_standing(self):
        response = create(make_user('newcomer'), {'name': 'Second'})

        assert response.status_code == 403
        assert response.json()['code'] == 'workspace_create_forbidden'
        assert not Workspace.objects.filter(slug='second').exists()

    def test_the_account_row_is_what_gets_locked_first(self, monkeypatch):
        locked = []
        select_for_update = QuerySet.select_for_update

        def record(queryset, *args, **kwargs):
            locked.append(queryset.model)
            return select_for_update(queryset, *args, **kwargs)

        monkeypatch.setattr(QuerySet, 'select_for_update', record)

        response = create(admin_elsewhere('founder'), {'name': 'Second'})

        assert response.status_code == 201, response.data
        assert locked[0] is User


class TestWhatACreateMakes:
    @pytest.mark.parametrize('rest', [
        {},
        {'slug': '', 'country': '', 'currency': '', 'language': ''},
        {'slug': None, 'country': None, 'currency': None, 'language': None},
    ], ids=['left-out', 'blank', 'null'])
    def test_a_chinese_name_gets_a_generated_slug_and_a_workspace_ready_to_sell_from(self, queued, rest):
        user = admin_elsewhere('founder')

        response = create(user, {'name': '极客小店', **rest})

        assert response.status_code == 201, response.data
        workspace = Workspace.objects.get(pk=response.json()['id'])
        # Nothing of the name survives slugify.
        assert re.fullmatch(r'ws-[0-9a-f]{8}', workspace.slug)
        assert workspace.name == '极客小店'

        # No locale was asked for and there is no current workspace to copy one from.
        assert locale_of(workspace.id) == ('', 'USD', 'en')
        assert Settings.objects.get(workspace=workspace).site_name == '极客小店'
        assert Currency.objects.filter(code='USD', is_active=True).exists()
        assert list(Store.all_objects.filter(workspace=workspace).values_list('code', 'is_active')) == [('main', True)]
        templates = MessageTemplate.objects.filter(workspace=workspace)
        assert sorted(templates.values_list('code', flat=True)) == sorted(NOTIFICATION_CODES)

        owner = PlatformMembership.objects.get(profile__workspace=workspace)
        assert (owner.user, owner.role, owner.is_active) == (user, 'owner', True)
        assert StaffMember.all_objects.get(workspace=workspace, user=user).role.code == 'admin'
        assert WorkspacePlatformProfile.objects.filter(workspace=workspace).count() == 1
        operation = WorkspaceOperation.objects.get(workspace=workspace)
        assert (operation.operation, operation.status, operation.initiated_by) == ('create', 'completed', user)
        assert operation.completed_at is not None
        # Nothing is left to a worker.
        assert queued == []

    def test_the_created_workspace_is_returned_as_me_lists_it(self):
        user = admin_elsewhere('founder')

        response = create(user, {'name': 'Geeker Outlet'})

        assert response.status_code == 201, response.data
        created = response.json()
        assert set(created) == ME_WORKSPACE_FIELDS
        assert created == {item['id']: item for item in get_me(user)['workspaces']}[created['id']]
        assert (created['slug'], created['status']) == ('geeker-outlet', 'active')
        assert (created['role'], created['is_member'], created['is_owner']) == ('admin', True, True)

    def test_a_slug_that_is_asked_for_and_taken_is_refused(self):
        user = admin_elsewhere('founder')
        make_workspace('outlet')

        response = create(user, {'name': 'Geeker Outlet', 'slug': 'outlet'})

        assert response.status_code == 400
        assert 'slug' in response.json()
        assert not Workspace.objects.filter(name='Geeker Outlet').exists()

    def test_a_slug_made_from_a_name_that_is_taken_gets_a_suffix(self):
        user = admin_elsewhere('founder')
        make_workspace('geeker-outlet')

        response = create(user, {'name': 'Geeker Outlet'})

        assert response.status_code == 201, response.data
        assert re.fullmatch(r'geeker-outlet-[0-9a-f]{4}', response.json()['slug'])

    @pytest.mark.parametrize('field, value', [('country', 'NZL'), ('currency', 'ZZZ'), ('language', 'fr')])
    def test_a_locale_the_platform_cannot_serve_is_refused(self, field, value):
        user = admin_elsewhere('founder')

        response = create(user, {'name': 'Elsewhere', field: value})

        assert response.status_code == 400
        assert field in response.json()
        assert not Workspace.objects.filter(slug='elsewhere').exists()
        assert not Currency.objects.filter(code='ZZZ').exists()


class TestLocaleOfTheCurrentWorkspace:
    """The workspace the caller's token was minted for lends its locale to the new one."""

    @pytest.fixture
    def current(self):
        workspace = make_workspace('current')
        Settings.objects.filter(workspace=workspace).update(
            country='NZ', default_currency='NZD', default_language='zh-hans',
        )
        return workspace

    def test_country_currency_and_language_are_copied_from_it(self, current):
        user = make_user('founder')
        join(current, user, 'staff')
        join(make_workspace('elsewhere'), user, 'admin')

        response = create(user, {'name': 'Second'}, workspace=current)

        assert response.status_code == 201, response.data
        workspace_id = response.json()['id']
        assert locale_of(workspace_id) == ('NZ', 'NZD', 'zh-hans')
        assert Currency.objects.filter(code='NZD', is_active=True).exists()
        templates = MessageTemplate.objects.filter(workspace_id=workspace_id)
        assert set(templates.values_list('language', flat=True)) == {'zh-hans'}
        assert '合计 NZ$' in templates.get(code='order_created').app_message_body

    def test_values_in_the_request_come_first(self, current):
        user = make_user('founder')
        assign_workspace_owner(current, user)

        response = create(
            user, {'name': 'Second', 'country': 'au', 'currency': 'aud', 'language': ''}, workspace=current,
        )

        assert response.status_code == 201, response.data
        assert locale_of(response.json()['id']) == ('AU', 'AUD', 'zh-hans')
        assert Currency.objects.filter(code='AUD', is_active=True).exists()

    def test_a_workspace_the_caller_has_left_lends_nothing(self, current):
        user = admin_elsewhere('founder')
        join(current, user, 'admin', is_active=False)

        response = create(user, {'name': 'Second'}, workspace=current)

        assert response.status_code == 201, response.data
        assert locale_of(response.json()['id']) == ('', 'USD', 'en')


class TestBrokerDown:
    @pytest.fixture
    def publishes(self, monkeypatch):
        """Every task publish fails, as it does when the broker is unreachable; ``.delay`` goes through here too."""
        attempts = []

        def refuse(task, *args, **kwargs):
            attempts.append(task.name)
            raise OperationalError('broker unreachable')

        monkeypatch.setattr(Task, 'apply_async', refuse)
        return attempts

    @pytest.fixture(params=['after-commit', 'at-once'])
    def listener_that_queues(self, request):
        """A ``workspace.created`` listener that queues a task once the transaction commits, or straight away.

        bfg's own listeners for the event queue nothing, so this one stands in for
        one that does, making sure a publish on this path really happens.
        """
        def listener(event):
            publish = partial(deliver_ga4_events.delay, event['data']['workspace'].id, {'events': []})
            if request.param == 'after-commit':
                after_commit(publish)
            else:
                publish()

        global_dispatcher.listen('workspace.created', listener)
        yield
        global_dispatcher.remove_listener('workspace.created', listener)

    def test_the_request_and_the_workspace_survive_it(
        self, publishes, listener_that_queues, django_capture_on_commit_callbacks,
    ):
        user = admin_elsewhere('founder')

        # Test transactions never commit, so the callbacks are run here instead.
        with django_capture_on_commit_callbacks(execute=True):
            response = create(user, {'name': 'Offline Shop'})

        assert response.status_code == 201, response.data
        # The listener's publish was tried and failed, and it was the only one:
        # provisioning itself queues nothing.
        assert publishes == [deliver_ga4_events.name]
        workspace = Workspace.objects.get(pk=response.json()['id'])
        assert Store.all_objects.filter(workspace=workspace, code='main', is_active=True).exists()
        assert locale_of(workspace.id) == ('', 'USD', 'en')
        assert Currency.objects.filter(code='USD', is_active=True).exists()
        assert MessageTemplate.objects.filter(workspace=workspace).count() == len(NOTIFICATION_CODES)
        assert PlatformMembership.objects.filter(
            profile__workspace=workspace, user=user, role='owner', is_active=True,
        ).exists()
        assert WorkspaceOperation.objects.get(workspace=workspace).status == 'completed'


class TestMe:
    @pytest.mark.parametrize('standing, blocked', [
        ('admin-elsewhere', None),
        ('at-the-limit', 'workspace_limit_reached'),
        ('no-standing', 'workspace_create_forbidden'),
    ])
    def test_create_blocked_is_what_a_create_request_meets(self, settings, standing, blocked):
        settings.BFG_MAX_OWNED_WORKSPACES_PER_USER = 2
        user = make_user('caller')
        if standing == 'admin-elsewhere':
            join(make_workspace('shop'), user, 'admin')
        elif standing == 'at-the-limit':
            closed = make_workspace('closed')
            assign_workspace_owner(closed, user)
            suspend_workspace(closed)
            assign_workspace_owner(make_workspace('open'), user)

        body = get_me(user)

        assert (body['workspace_limit'], body['create_blocked']) == (2, blocked)
        response = create(user, {'name': 'Next'})
        if blocked is None:
            assert response.status_code == 201, response.data
        else:
            assert response.json()['code'] == blocked

    def test_the_limit_defaults_to_three(self):
        body = get_me(admin_elsewhere('caller'))

        assert (body['workspace_limit'], body['create_blocked']) == (3, None)

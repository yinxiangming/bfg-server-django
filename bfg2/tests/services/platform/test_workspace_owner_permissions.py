"""
Workspace owners on ``/api/v1/platform/workspaces/``.

A workspace's owner holds an active owner ``PlatformMembership``, recorded apart from
staff roles (``bfg.platform.services.ownership``). The viewset reaches every workspace
the caller is staff of or owns, so an owner still reaches a workspace they are not
staff of, or one that is suspended, and only the owner may change its details.
``me/`` lists the same workspaces with the caller's standing in each.
"""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, Workspace, WorkspaceDomain
from bfg.platform.models import PlatformMembership, WorkspacePlatformProfile
from bfg.platform.services.ownership import assign_workspace_owner
from bfg.platform.services.provision_service import suspend_workspace

User = get_user_model()
pytestmark = pytest.mark.django_db

WORKSPACES_URL = '/api/v1/platform/workspaces/'
ME_URL = '/api/v1/platform/workspaces/me/'

# Every workspace in ``me/`` carries exactly these.
ME_WORKSPACE_FIELDS = {
    'id', 'name', 'slug', 'created_at', 'domain', 'status', 'suspended_at',
    'role', 'role_name', 'is_member', 'is_owner', 'plan', 'credits', 'extensions',
}


@pytest.fixture(autouse=True)
def platform_workspace(settings, db):
    """Embedded mode with a real management workspace."""
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = 'platform'
    return Workspace.objects.create(name='Platform', slug='platform', is_active=True)


@pytest.fixture
def shop():
    return Workspace.objects.create(
        name='Shop', slug='shop', email='hello@shop.test', phone='09 000 000',
        settings={'theme': 'store'}, is_active=True,
    )


def make_workspace(slug, **fields):
    return Workspace.objects.create(name=slug.title(), slug=slug, **fields)


def make_user(username):
    return User.objects.create_user(username=username, password='x')


def join(workspace, user, role_code, is_active=True, joined_at=None):
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code=role_code, defaults={'name': role_code})
    StaffMember.all_objects.create(
        workspace=workspace, user=user, role=role, is_active=is_active, created_at=joined_at or timezone.now(),
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def listed(response):
    data = response.data
    return data['results'] if isinstance(data, dict) else data


def get_me(user):
    response = client_for(user).get(ME_URL)
    assert response.status_code == 200, response.data
    return response.json()


class TestOnlyTheOwnerUpdatesAWorkspace:
    @pytest.mark.parametrize('owner_role', [None, 'admin'], ids=['owner-not-staff', 'owner-and-admin'])
    def test_the_owner_changes_name_email_and_phone_and_nothing_else(self, shop, owner_role):
        owner = make_user('owner')
        assign_workspace_owner(shop, owner)
        if owner_role:
            join(shop, owner, owner_role)

        response = client_for(owner).patch(f'{WORKSPACES_URL}{shop.id}/', {
            'name': 'Renamed',
            'email': 'owner@shop.test',
            'phone': '09 111 222',
            'slug': 'taken',
            'is_active': False,
            'settings': {'theme': 'website'},
        }, format='json')

        assert response.status_code == 200, response.data
        shop.refresh_from_db()
        assert (shop.name, shop.email, shop.phone) == ('Renamed', 'owner@shop.test', '09 111 222')
        assert (shop.slug, shop.is_active, shop.settings) == ('shop', True, {'theme': 'store'})

    @pytest.mark.parametrize('role_code', ['admin', 'customer_service'])
    def test_staff_who_do_not_own_the_workspace_are_refused(self, shop, role_code):
        assign_workspace_owner(shop, make_user('owner'))
        staff = make_user(f'{role_code}-user')
        join(shop, staff, role_code)

        response = client_for(staff).patch(f'{WORKSPACES_URL}{shop.id}/', {'name': 'Renamed'}, format='json')

        assert response.status_code == 403
        body = response.json()
        assert set(body) == {'detail', 'code'}
        assert body['code'] == 'workspace_owner_required'
        shop.refresh_from_db()
        assert shop.name == 'Shop'

    def test_a_workspace_the_caller_neither_staffs_nor_owns_is_not_found(self, shop):
        outsider = make_user('outsider')
        elsewhere = make_workspace('elsewhere')
        join(elsewhere, outsider, 'admin')
        assign_workspace_owner(elsewhere, outsider)
        # A staff membership that has ended reaches nothing either.
        join(shop, outsider, 'admin', is_active=False)

        response = client_for(outsider).patch(f'{WORKSPACES_URL}{shop.id}/', {'name': 'Renamed'}, format='json')

        assert response.status_code == 404
        shop.refresh_from_db()
        assert shop.name == 'Shop'


class TestOwnersReachTheirWorkspaces:
    def test_the_owner_of_a_suspended_workspace_reaches_it_without_being_staff(self, shop):
        owner = make_user('owner')
        join(shop, owner, 'customer_service')
        closed = make_workspace('closed')
        assign_workspace_owner(closed, owner)
        suspend_workspace(closed)
        join(make_workspace('others'), make_user('other-admin'), 'admin')
        client = client_for(owner)

        workspaces = client.get(WORKSPACES_URL)
        detail = client.get(f'{WORKSPACES_URL}{closed.id}/')

        assert workspaces.status_code == 200, workspaces.data
        assert sorted(item['slug'] for item in listed(workspaces)) == ['closed', 'shop']
        assert detail.status_code == 200, detail.data
        assert detail.data['is_active'] is False


class TestMe:
    def test_lists_owned_workspaces_with_the_callers_standing_in_each(self, shop):
        member = make_user('member')
        join(shop, member, 'admin')
        both = make_workspace('both')
        join(both, member, 'admin')
        assign_workspace_owner(both, member)
        closed = make_workspace('closed')
        assign_workspace_owner(closed, member)
        suspend_workspace(closed)
        dormant = make_workspace('dormant', is_active=False)
        assign_workspace_owner(dormant, member)
        others = make_workspace('others')
        join(others, make_user('other-admin'), 'admin')
        assign_workspace_owner(others, make_user('other-owner'))

        workspaces = get_me(member)['workspaces']

        standing = {
            item['slug']: (
                item['role'], item['is_member'], item['is_owner'], item['status'], item['suspended_at'] is not None,
            )
            for item in workspaces
        }
        assert len(workspaces) == len(standing)
        assert standing == {
            'shop': ('admin', True, False, 'active', False),
            'both': ('admin', True, True, 'active', False),
            # Owned without being staff: suspended, and closed with no suspension on record.
            'closed': (None, False, True, 'suspended', True),
            'dormant': (None, False, True, 'inactive', False),
        }

    @pytest.mark.parametrize('embedded', [True, False], ids=['embedded', 'standalone'])
    def test_each_workspace_carries_exactly_the_agreed_fields(self, settings, shop, embedded):
        settings.PLATFORM_EMBEDDED = embedded
        member = make_user('member')
        join(shop, member, 'admin')
        assign_workspace_owner(shop, member)
        WorkspaceDomain.objects.create(
            workspace=shop,
            hostname='shop.example.test',
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
            ssl_status=WorkspaceDomain.SSL_ACTIVE,
            is_primary=True,
        )
        bare = make_workspace('bare')
        assign_workspace_owner(bare, member)

        body = get_me(member)

        assert set(body) == {'is_platform_admin', 'workspaces', 'workspace_limit', 'create_blocked'}
        by_slug = {item['slug']: item for item in body['workspaces']}
        assert set(by_slug) == {'shop', 'bare'}
        for item in by_slug.values():
            assert set(item) == ME_WORKSPACE_FIELDS
            assert (item['plan'], item['credits'], item['extensions']) == (None, None, [])
        assert (by_slug['shop']['id'], by_slug['shop']['name']) == (shop.id, 'Shop')
        assert parse_datetime(by_slug['shop']['created_at']) == shop.created_at
        assert by_slug['shop']['domain'] == 'shop.example.test'
        assert by_slug['bare']['domain'] is None

    def test_each_role_comes_with_the_name_the_workspace_gave_it(self, shop):
        member = make_user('member')
        florist = StaffRole.objects.create(workspace=shop, code='florist', name='Head Florist')
        StaffMember.all_objects.create(workspace=shop, user=member, role=florist, is_active=True)
        owned = make_workspace('owned')
        assign_workspace_owner(owned, member)

        roles = {item['slug']: (item['role'], item['role_name']) for item in get_me(member)['workspaces']}

        # Owned without being staff: no role, and so no name.
        assert roles == {'shop': ('florist', 'Head Florist'), 'owned': (None, None)}

    def test_standalone_names_a_membership_role_by_its_label(self, settings, shop):
        settings.PLATFORM_EMBEDDED = False
        member = make_user('member')
        PlatformMembership.objects.create(
            user=member, profile=WorkspacePlatformProfile.objects.create(workspace=shop), role='staff',
        )

        [item] = get_me(member)['workspaces']

        assert (item['role'], item['role_name']) == ('staff', 'Staff')

    def test_memberships_come_first_in_their_order_then_workspaces_only_owned(self):
        member = make_user('member')
        now = timezone.now()
        owned_only = make_workspace('owned-only')
        assign_workspace_owner(owned_only, member)
        first = make_workspace('first')
        join(first, member, 'admin', joined_at=now - timedelta(days=2))
        latest = make_workspace('latest')
        join(latest, member, 'staff', joined_at=now - timedelta(days=1))

        slugs = [item['slug'] for item in get_me(member)['workspaces']]

        # Memberships keep their newest-first order; a workspace the user owns
        # without being staff of it follows them, however old it is.
        assert slugs == ['latest', 'first', 'owned-only']

    def test_standalone_counts_platform_memberships_as_membership(self, settings, shop):
        settings.PLATFORM_EMBEDDED = False
        member = make_user('member')
        assign_workspace_owner(shop, member)
        helped = make_workspace('helped')
        PlatformMembership.objects.create(
            user=member, profile=WorkspacePlatformProfile.objects.create(workspace=helped), role='staff',
        )
        # A remote workspace with no local row has no id, name or slug to list it by.
        PlatformMembership.objects.create(user=member, profile=WorkspacePlatformProfile.objects.create(), role='staff')
        # A standalone platform does not take a local staff row for membership.
        join(make_workspace('local-staff'), member, 'admin')

        standing = {
            item['slug']: (item['role'], item['is_member'], item['is_owner'])
            for item in get_me(member)['workspaces']
        }

        assert standing == {
            'shop': ('owner', True, True),
            'helped': ('staff', True, False),
        }

"""
Who may write through ``/api/v1/platform/workspaces/``.

The endpoint sits on a public path, so no workspace is bound to the request, and
the viewset's queryset is every workspace the caller is staff of, whatever the
role, or owns. Only the owner may update a workspace, and two writes need more
than that:

* a custom domain decides which workspace a storefront hostname is served by, and
  hostnames are unique across the install, so neither create nor update takes one,
  not even from the owner;
* suspending or resuming takes a workspace offline, or back, for everyone in it,
  so only platform admins may do either.
"""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, StaffRole, Workspace, WorkspaceDomain
from bfg.platform.services.ownership import assign_workspace_owner

User = get_user_model()
pytestmark = pytest.mark.django_db

OTHER_HOST = 'shop.other.test'


@pytest.fixture(autouse=True)
def platform_workspace(settings, db):
    """Embedded mode with a real management workspace, so a refusal below is about
    who the caller is rather than a missing platform workspace."""
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = 'platform'
    return Workspace.objects.create(name='Platform', slug='platform', is_active=True)


@pytest.fixture
def other_shop():
    workspace = Workspace.objects.create(name='Other', slug='other', is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname=OTHER_HOST,
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )
    return workspace


@pytest.fixture
def own_shop():
    return Workspace.objects.create(name='Own', slug='own', is_active=True)


def join(workspace, user, role_code):
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code=role_code, defaults={'name': role_code})
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def staff_client(workspace, role_code, username):
    user = User.objects.create_user(username=username, password='x')
    join(workspace, user, role_code)
    return client_for(user)


def owner_client(workspace, username):
    user = User.objects.create_user(username=username, password='x')
    assign_workspace_owner(workspace, user)
    return client_for(user)


def assert_hostname_still_belongs_to(workspace):
    domain = WorkspaceDomain.objects.get(hostname=OTHER_HOST)
    assert domain.workspace_id == workspace.id
    assert domain.verification_status == WorkspaceDomain.VERIFICATION_VERIFIED
    assert domain.is_primary is True


class TestCustomDomainIsNotWritable:
    # Updates are the owner's alone, so it is the owner's request the domain rule has
    # to refuse; anyone else is turned away before the body is looked at.
    def test_update_refuses_another_workspaces_hostname(self, own_shop, other_shop):
        client = owner_client(own_shop, 'owner-user')

        response = client.patch(
            f'/api/v1/platform/workspaces/{own_shop.id}/', {'domain': OTHER_HOST}, format='json',
        )

        assert response.status_code == 400
        assert 'domain' in response.data
        assert_hostname_still_belongs_to(other_shop)
        assert not own_shop.domains.filter(kind=WorkspaceDomain.KIND_CUSTOM).exists()

    def test_update_refuses_an_unclaimed_hostname_too(self, own_shop):
        client = owner_client(own_shop, 'owner-user')

        response = client.patch(
            f'/api/v1/platform/workspaces/{own_shop.id}/', {'domain': 'fresh.own.test'}, format='json',
        )

        assert response.status_code == 400
        assert not WorkspaceDomain.objects.filter(hostname='fresh.own.test').exists()

    def test_update_still_saves_the_other_fields(self, own_shop):
        client = owner_client(own_shop, 'renamer')

        response = client.patch(f'/api/v1/platform/workspaces/{own_shop.id}/', {'name': 'Renamed'}, format='json')

        assert response.status_code == 200, response.data
        own_shop.refresh_from_db()
        assert own_shop.name == 'Renamed'

    def test_create_refuses_a_hostname(self, other_shop, monkeypatch):
        from bfg.platform.views import workspace_views

        queued = []
        monkeypatch.setattr(
            workspace_views, 'provision_workspace', SimpleNamespace(delay=lambda **kwargs: queued.append(kwargs)),
        )
        user = User.objects.create_user(username='creator', password='x')

        response = client_for(user).post(
            '/api/v1/platform/workspaces/',
            {'name': 'Newcomer', 'slug': 'newcomer', 'domain': OTHER_HOST},
            format='json',
        )

        assert response.status_code == 400
        assert 'domain' in response.data
        assert not Workspace.objects.filter(slug='newcomer').exists()
        assert queued == []
        assert_hostname_still_belongs_to(other_shop)


class TestSuspendAndResumeArePlatformAdminOnly:
    @pytest.mark.parametrize('role_code', ['customer_service', 'admin'])
    def test_workspace_staff_cannot_suspend(self, own_shop, role_code):
        client = staff_client(own_shop, role_code, f'{role_code}-suspender')

        response = client.post(f'/api/v1/platform/workspaces/{own_shop.id}/suspend/', {}, format='json')

        assert response.status_code == 403
        own_shop.refresh_from_db()
        assert own_shop.is_active is True

    @pytest.mark.parametrize('role_code', ['customer_service', 'admin'])
    def test_workspace_staff_cannot_resume(self, own_shop, role_code):
        client = staff_client(own_shop, role_code, f'{role_code}-resumer')
        Workspace.objects.filter(pk=own_shop.pk).update(is_active=False)

        response = client.post(f'/api/v1/platform/workspaces/{own_shop.id}/resume/', {}, format='json')

        assert response.status_code == 403
        own_shop.refresh_from_db()
        assert own_shop.is_active is False

    def test_a_platform_admin_can_suspend_and_resume(self, own_shop, platform_workspace):
        operator = User.objects.create_user(username='platform-operator', password='x')
        join(platform_workspace, operator, 'admin')
        # Being a platform admin does not widen the viewset's queryset: the operator
        # still reaches a workspace only as its staff or its owner.
        join(own_shop, operator, 'staff')
        client = client_for(operator)

        suspended = client.post(
            f'/api/v1/platform/workspaces/{own_shop.id}/suspend/', {'reason': 'maintenance'}, format='json',
        )
        own_shop.refresh_from_db()
        assert suspended.status_code == 200, suspended.data
        assert own_shop.is_active is False

        resumed = client.post(f'/api/v1/platform/workspaces/{own_shop.id}/resume/', {}, format='json')
        own_shop.refresh_from_db()
        assert resumed.status_code == 200, resumed.data
        assert own_shop.is_active is True

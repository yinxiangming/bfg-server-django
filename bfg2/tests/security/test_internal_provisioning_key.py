"""The internal provisioning endpoints refuse every call unless PLATFORM_API_KEY is set and presented."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import StaffMember, Workspace

User = get_user_model()

PROVISION_USER_URL = '/api/v1/internal/auth/provision-user/'
PROVISION_WORKSPACE_URL = '/api/v1/internal/auth/provision-workspace/'


@pytest.fixture
def victim(db):
    return User.objects.create_user(
        username='victim', email='victim@example.com', password='Secret-pass-123', is_active=True,
    )


@pytest.fixture
def shop(db):
    return Workspace.objects.create(name='Some Shop', slug='some-shop', is_active=True)


def _post(url, data, authorization=None):
    headers = {} if authorization is None else {'HTTP_AUTHORIZATION': authorization}
    return APIClient().post(url, data, format='json', **headers)


@pytest.mark.parametrize('configured', ['', None, 'absent'])
@pytest.mark.parametrize('authorization', [None, 'Bearer ', 'Bearer None', 'Bearer local-dev-key'])
def test_provision_user_refuses_every_call_without_a_configured_key(
    victim, shop, settings, configured, authorization,
):
    if configured != 'absent':
        settings.PLATFORM_API_KEY = configured

    res = _post(
        PROVISION_USER_URL,
        {'email': victim.email, 'workspace_slug': shop.slug, 'role': 'admin'},
        authorization,
    )

    assert res.status_code == 403
    assert 'token' not in res.data
    assert 'refresh' not in res.data
    assert not StaffMember.all_objects.filter(user=victim).exists()


@pytest.mark.parametrize('authorization', [None, 'Bearer ', 'Bearer wrong-key', 'the-platform-key'])
def test_provision_user_refuses_a_missing_or_wrong_key(victim, shop, settings, authorization):
    settings.PLATFORM_API_KEY = 'the-platform-key'

    res = _post(
        PROVISION_USER_URL,
        {'email': victim.email, 'workspace_slug': shop.slug, 'role': 'admin'},
        authorization,
    )

    assert res.status_code == 403
    assert not StaffMember.all_objects.filter(user=victim).exists()


def test_provision_user_accepts_the_configured_key(victim, settings):
    settings.PLATFORM_API_KEY = 'the-platform-key'

    res = _post(PROVISION_USER_URL, {'email': victim.email}, 'Bearer the-platform-key')

    assert res.status_code == 200
    assert res.data['token']


@pytest.mark.parametrize('configured', ['', None, 'absent'])
def test_provision_workspace_refuses_every_call_without_a_configured_key(db, settings, configured):
    if configured != 'absent':
        settings.PLATFORM_API_KEY = configured

    res = _post(
        PROVISION_WORKSPACE_URL,
        {'email': 'new-owner@example.com', 'workspace_name': 'Free Shop', 'workspace_slug': 'free-shop'},
        'Bearer ',
    )

    assert res.status_code == 403
    assert not Workspace.objects.filter(slug='free-shop').exists()
    assert not User.objects.filter(email='new-owner@example.com').exists()


def test_provision_workspace_accepts_the_configured_key(db, settings):
    settings.PLATFORM_API_KEY = 'the-platform-key'

    res = _post(
        PROVISION_WORKSPACE_URL,
        {'email': 'new-owner@example.com', 'workspace_name': 'Free Shop', 'workspace_slug': 'free-shop'},
        'Bearer the-platform-key',
    )

    assert res.status_code == 201
    assert Workspace.objects.filter(slug='free-shop').exists()

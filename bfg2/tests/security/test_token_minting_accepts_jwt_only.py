"""Endpoints that mint tokens take a JWT as the caller's sign-in, and nothing else.

switch-workspace and token-exchange return a token for the caller, and sso/start
a one-time code that sso/exchange turns into a token pair. An API key, a session
or basic credentials are not a sign-in to trade for one: a workspace API key
would otherwise mint a full JWT for the user who created the key.
"""

import base64

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from bfg.common.models import APIKey, StaffMember, StaffRole, Workspace, WorkspaceDomain
from bfg.platform.models import PlatformMembership, PlatformSSOCode, WorkspacePlatformProfile
from bfg.platform.views.auth_views import AuthViewSet
from bfg.platform.views.switch_workspace_view import switch_workspace
from config.serializers import CustomTokenObtainPairSerializer

User = get_user_model()

PASSWORD = 'Secret-pass-123'

# name: (path, PLATFORM_EMBEDDED, the response field that carries what was minted)
ENDPOINTS = {
    'switch-workspace': ('/api/v1/platform/switch-workspace/', False, 'access'),
    'token-exchange': ('/api/v1/platform/auth/token-exchange/', True, 'workspace_token'),
    'sso-start': ('/api/v1/platform/auth/sso/start/', False, 'redirect_url'),
}


@pytest.fixture(autouse=True)
def _deployed_authentication(production_authentication):
    production_authentication(switch_workspace.cls, AuthViewSet)


@pytest.fixture
def workspace(db):
    workspace = Workspace.objects.create(name='Acme', slug='acme', is_active=True)
    WorkspaceDomain.objects.create(
        workspace=workspace,
        hostname='portal.acme.test',
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
        is_primary=True,
    )
    return workspace


@pytest.fixture
def member(workspace):
    """Staff of ``workspace``, and its member on the platform side too."""
    user = User.objects.create_user(
        username='member', email='member@example.com', password=PASSWORD, is_active=True,
    )
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    profile = WorkspacePlatformProfile.objects.create(workspace=workspace, region='apac')
    PlatformMembership.objects.create(user=user, profile=profile, role='owner', is_active=True)
    return user


def _client_presenting(credential, user, workspace):
    client = APIClient()
    if credential == 'jwt':
        access = CustomTokenObtainPairSerializer.get_token(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
    elif credential == 'api_key':
        key, secret = APIKey.create_key(workspace, 'integration', created_by=user)
        client.credentials(HTTP_X_API_KEY=key.prefix, HTTP_X_API_SECRET=secret)
    elif credential == 'basic':
        basic = base64.b64encode(f'{user.username}:{PASSWORD}'.encode()).decode()
        client.credentials(HTTP_AUTHORIZATION=f'Basic {basic}')
    elif credential == 'session':
        client.force_login(user)
    return client


def _post(endpoint, client, workspace, settings):
    path, embedded, _ = ENDPOINTS[endpoint]
    settings.PLATFORM_EMBEDDED = embedded
    return client.post(path, {'workspace_id': workspace.id}, format='json')


@pytest.mark.parametrize('credential', ['api_key', 'session', 'basic'])
@pytest.mark.parametrize('endpoint', sorted(ENDPOINTS))
def test_only_a_jwt_is_a_sign_in_that_mints(member, workspace, settings, endpoint, credential):
    res = _post(endpoint, _client_presenting(credential, member, workspace), workspace, settings)

    assert res.status_code == 401
    assert ENDPOINTS[endpoint][2] not in res.data
    assert 'refresh' not in res.data
    assert not PlatformSSOCode.objects.exists()


@pytest.mark.parametrize('endpoint', sorted(ENDPOINTS))
def test_a_jwt_still_mints(member, workspace, settings, endpoint):
    res = _post(endpoint, _client_presenting('jwt', member, workspace), workspace, settings)

    assert res.status_code == 200, res.data
    assert res.data[ENDPOINTS[endpoint][2]]

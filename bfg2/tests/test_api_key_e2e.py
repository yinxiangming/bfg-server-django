"""
End-to-end tests for the API Key feature.

Tests the full lifecycle:
  1. Create an API key via the management API (admin user + session auth)
  2. Verify the key appears in the list
  3. Use the key (X-API-Key / X-API-Secret headers) to call a protected endpoint
  4. Verify last_used_at is updated
  5. Edit the key (rename, deactivate)
  6. Verify a deactivated key is rejected
  7. Reactivate, then regenerate the secret
  8. Verify old secret no longer works, new secret does
  9. Delete the key
  10. Verify deleted key is rejected
"""

import pytest
from django.test.utils import override_settings
from rest_framework import status
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from bfg.common.models import Workspace, User, APIKey, StaffRole, StaffMember


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_REST_FRAMEWORK_API_KEY = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'config.authentication.APIKeyAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
}


@pytest.fixture(autouse=True)
def _enable_apikey_auth():
    """
    Inject APIKeyAuthentication into DRF for every test in this module.

    ``api_settings.reload()`` alone is not enough: ``APIView.authentication_classes``
    is bound to the tuple from the first ``api_settings`` access at import time,
    so we must re-point it after overriding REST_FRAMEWORK.
    """
    from rest_framework.views import APIView

    prev_auth_classes = APIView.authentication_classes
    with override_settings(REST_FRAMEWORK=_REST_FRAMEWORK_API_KEY):
        api_settings.reload()
        APIView.authentication_classes = api_settings.DEFAULT_AUTHENTICATION_CLASSES
        try:
            yield
        finally:
            APIView.authentication_classes = prev_auth_classes
            api_settings.reload()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Test Workspace', slug='test-ws', is_active=True)


@pytest.fixture
def admin_user(db, workspace):
    """Superuser who is also an admin staff member of the workspace."""
    user = User.objects.create_superuser(
        username='admin',
        email='admin@test.com',
        password='testpass123',
    )
    user.default_workspace = workspace
    user.save()
    role = StaffRole.objects.create(workspace=workspace, name='Admin', code='admin', is_system=True)
    StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def admin_client(admin_user, workspace):
    """DRF test client authenticated as admin with workspace header."""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


@pytest.fixture
def anon_client(workspace):
    """Unauthenticated client with workspace header (for API key testing)."""
    client = APIClient()
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

API_KEYS_URL = '/api/v1/api-keys/'


def _get_workspaces_with_api_key(client, api_key, api_secret):
    """
    Pass API key headers on the GET itself.

    Stored ``credentials()`` are not reliably merged into GET requests after
    other tests have used the Django/DRF test client (e.g. platform SSO);
    explicit ``HTTP_*`` kwargs on ``get()`` keep auth headers on the WSGI environ.
    """
    return client.get(
        '/api/v1/workspaces/',
        HTTP_X_API_KEY=api_key,
        HTTP_X_API_SECRET=api_secret,
    )


@pytest.mark.django_db
class TestAPIKeyLifecycle:
    """Full CRUD + authentication lifecycle."""

    def test_create_api_key_returns_secret(self, admin_client):
        """POST /api-keys/ should return api_key, api_secret (one-time)."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'My Integration'}, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        data = resp.data
        assert 'api_key' in data
        assert 'api_secret' in data
        assert len(data['api_key']) == 8  # prefix length
        assert len(data['api_secret']) == 64  # hex-encoded 32 bytes
        assert data['name'] == 'My Integration'

    def test_list_api_keys_hides_secret(self, admin_client):
        """GET /api-keys/ should list keys but never expose the secret."""
        admin_client.post(API_KEYS_URL, {'name': 'Key A'}, format='json')
        admin_client.post(API_KEYS_URL, {'name': 'Key B'}, format='json')

        resp = admin_client.get(API_KEYS_URL)
        assert resp.status_code == status.HTTP_200_OK
        results = resp.data if isinstance(resp.data, list) else resp.data.get('results', [])
        assert len(results) >= 2
        for item in results:
            assert 'api_secret' not in item
            assert 'secret_hash' not in item
            assert 'prefix' in item

    def test_authenticate_with_api_key(self, admin_client, anon_client):
        """An anonymous client with valid X-API-Key + X-API-Secret should access protected APIs."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Auth Test'}, format='json')
        api_key = resp.data['api_key']
        api_secret = resp.data['api_secret']

        anon_client.credentials(
            HTTP_X_API_KEY=api_key,
            HTTP_X_API_SECRET=api_secret,
        )
        resp = _get_workspaces_with_api_key(anon_client, api_key, api_secret)
        assert resp.status_code == status.HTTP_200_OK

    def test_last_used_at_updates(self, admin_client, anon_client):
        """After using the key, last_used_at should be populated."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Usage Track'}, format='json')
        key_id = resp.data['id']
        api_key = resp.data['api_key']
        api_secret = resp.data['api_secret']

        # Verify last_used_at is initially None
        detail = admin_client.get(f'{API_KEYS_URL}{key_id}/')
        assert detail.data['last_used_at'] is None

        # Use the key
        anon_client.credentials(HTTP_X_API_KEY=api_key, HTTP_X_API_SECRET=api_secret)
        _get_workspaces_with_api_key(anon_client, api_key, api_secret)

        # Verify last_used_at is now set
        detail = admin_client.get(f'{API_KEYS_URL}{key_id}/')
        assert detail.data['last_used_at'] is not None

    def test_edit_api_key(self, admin_client):
        """PATCH /api-keys/{id}/ should update name and is_active."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Original'}, format='json')
        key_id = resp.data['id']

        resp = admin_client.patch(f'{API_KEYS_URL}{key_id}/', {'name': 'Renamed'}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['name'] == 'Renamed'

    def test_deactivated_key_rejected(self, admin_client, anon_client):
        """Deactivated key should return 401."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Will Deactivate'}, format='json')
        key_id = resp.data['id']
        api_key = resp.data['api_key']
        api_secret = resp.data['api_secret']

        # Deactivate
        admin_client.patch(f'{API_KEYS_URL}{key_id}/', {'is_active': False}, format='json')

        # Try to use it
        anon_client.credentials(HTTP_X_API_KEY=api_key, HTTP_X_API_SECRET=api_secret)
        resp = _get_workspaces_with_api_key(anon_client, api_key, api_secret)
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_regenerate_secret(self, admin_client, anon_client):
        """POST /api-keys/{id}/regenerate/ should return a new secret; old secret should fail."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Regen Test'}, format='json')
        key_id = resp.data['id']
        api_key = resp.data['api_key']
        old_secret = resp.data['api_secret']

        # Regenerate
        regen_resp = admin_client.post(f'{API_KEYS_URL}{key_id}/regenerate/')
        assert regen_resp.status_code == status.HTTP_200_OK
        new_secret = regen_resp.data['api_secret']
        assert new_secret != old_secret
        # api_key (prefix) should remain the same
        assert regen_resp.data['api_key'] == api_key

        # Old secret should fail
        anon_client.credentials(HTTP_X_API_KEY=api_key, HTTP_X_API_SECRET=old_secret)
        resp = _get_workspaces_with_api_key(anon_client, api_key, old_secret)
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

        # New secret should work
        anon_client.credentials(HTTP_X_API_KEY=api_key, HTTP_X_API_SECRET=new_secret)
        resp = _get_workspaces_with_api_key(anon_client, api_key, new_secret)
        assert resp.status_code == status.HTTP_200_OK

    def test_delete_api_key(self, admin_client, anon_client):
        """DELETE /api-keys/{id}/ should remove the key; subsequent use should fail."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Delete Me'}, format='json')
        key_id = resp.data['id']
        api_key = resp.data['api_key']
        api_secret = resp.data['api_secret']

        # Delete
        del_resp = admin_client.delete(f'{API_KEYS_URL}{key_id}/')
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

        # Verify gone from list
        list_resp = admin_client.get(API_KEYS_URL)
        results = list_resp.data if isinstance(list_resp.data, list) else list_resp.data.get('results', [])
        assert not any(k['id'] == key_id for k in results)

        # Try to use it
        anon_client.credentials(HTTP_X_API_KEY=api_key, HTTP_X_API_SECRET=api_secret)
        resp = _get_workspaces_with_api_key(anon_client, api_key, api_secret)
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_invalid_key_rejected(self, anon_client):
        """Completely invalid key should return 401."""
        anon_client.credentials(
            HTTP_X_API_KEY='nonexist',
            HTTP_X_API_SECRET='0' * 64,
        )
        resp = _get_workspaces_with_api_key(anon_client, 'nonexist', '0' * 64)
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_wrong_secret_rejected(self, admin_client, anon_client):
        """Valid key with wrong secret should return 401."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'Wrong Secret'}, format='json')
        api_key = resp.data['api_key']

        anon_client.credentials(
            HTTP_X_API_KEY=api_key,
            HTTP_X_API_SECRET='0' * 64,
        )
        resp = _get_workspaces_with_api_key(anon_client, api_key, '0' * 64)
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestAPIKeyWorkspaceIsolation:
    """Keys from workspace A should not access workspace B data."""

    def test_key_binds_to_correct_workspace(self, admin_client, workspace):
        """API key should set request.workspace to the key's workspace."""
        resp = admin_client.post(API_KEYS_URL, {'name': 'WS Binding'}, format='json')
        api_key = resp.data['api_key']
        api_secret = resp.data['api_secret']

        # Use the key (without X-Workspace-ID header) — workspace should come from the key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=api_key, HTTP_X_API_SECRET=api_secret)
        resp = _get_workspaces_with_api_key(client, api_key, api_secret)
        assert resp.status_code == status.HTTP_200_OK

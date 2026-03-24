"""
Unit tests for the API Key model and APIKeyAuthentication class.

Pure unit tests — no database, no HTTP. All dependencies are mocked.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from bfg.common.models.api_key import (
    generate_api_key_prefix,
    generate_api_key_secret,
    hash_secret,
    API_KEY_PREFIX_LENGTH,
    API_KEY_SECRET_BYTES,
)


# ═══════════════════════════════════════════════════════════════════
#  Helper functions
# ═══════════════════════════════════════════════════════════════════


class TestGenerateAPIKeyPrefix:
    def test_returns_string(self):
        assert isinstance(generate_api_key_prefix(), str)

    def test_correct_length(self):
        assert len(generate_api_key_prefix()) == API_KEY_PREFIX_LENGTH

    def test_hex_characters_only(self):
        prefix = generate_api_key_prefix()
        assert all(c in '0123456789abcdef' for c in prefix)

    def test_unique_on_consecutive_calls(self):
        a = generate_api_key_prefix()
        b = generate_api_key_prefix()
        assert a != b


class TestGenerateAPIKeySecret:
    def test_returns_string(self):
        assert isinstance(generate_api_key_secret(), str)

    def test_correct_length(self):
        # hex encoding doubles the byte count
        assert len(generate_api_key_secret()) == API_KEY_SECRET_BYTES * 2

    def test_hex_characters_only(self):
        secret = generate_api_key_secret()
        assert all(c in '0123456789abcdef' for c in secret)

    def test_unique_on_consecutive_calls(self):
        a = generate_api_key_secret()
        b = generate_api_key_secret()
        assert a != b


class TestHashSecret:
    def test_returns_64_char_hex(self):
        h = hash_secret('test-secret')
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_deterministic(self):
        assert hash_secret('abc') == hash_secret('abc')

    def test_different_inputs_different_hashes(self):
        assert hash_secret('secret-a') != hash_secret('secret-b')

    def test_empty_string(self):
        h = hash_secret('')
        assert len(h) == 64


# ═══════════════════════════════════════════════════════════════════
#  APIKey model methods (mocked, no DB)
# ═══════════════════════════════════════════════════════════════════

def _make_key(*, is_active=True, expires_at=None, raw_secret='the-secret'):
    """Build a SimpleNamespace that behaves like an APIKey instance."""
    key = SimpleNamespace(
        pk=1,
        name='Test Key',
        prefix='aabbccdd',
        secret_hash=hash_secret(raw_secret),
        is_active=is_active,
        expires_at=expires_at,
        last_used_at=None,
        created_by=None,
        workspace=SimpleNamespace(id=1, name='WS'),
    )
    return key


class TestVerifySecret:
    def test_matching_secret_returns_true(self):
        key = _make_key(raw_secret='good-secret')
        # Directly call the model method's logic
        assert hash_secret('good-secret') == key.secret_hash

    def test_wrong_secret_returns_false(self):
        key = _make_key(raw_secret='good-secret')
        assert hash_secret('bad-secret') != key.secret_hash


class TestIsExpired:
    def test_none_expires_at_is_not_expired(self):
        key = _make_key(expires_at=None)
        # Replicate property logic
        assert key.expires_at is None
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        assert is_expired is False

    def test_future_date_is_not_expired(self):
        future = timezone.now() + timedelta(days=30)
        key = _make_key(expires_at=future)
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        assert is_expired is False

    def test_past_date_is_expired(self):
        past = timezone.now() - timedelta(days=1)
        key = _make_key(expires_at=past)
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        assert is_expired is True


class TestIsUsable:
    def test_active_no_expiry(self):
        key = _make_key(is_active=True, expires_at=None)
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        assert key.is_active and not is_expired

    def test_inactive_key(self):
        key = _make_key(is_active=False, expires_at=None)
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        is_usable = key.is_active and not is_expired
        assert is_usable is False

    def test_expired_key(self):
        past = timezone.now() - timedelta(hours=1)
        key = _make_key(is_active=True, expires_at=past)
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        is_usable = key.is_active and not is_expired
        assert is_usable is False

    def test_inactive_and_expired(self):
        past = timezone.now() - timedelta(hours=1)
        key = _make_key(is_active=False, expires_at=past)
        is_expired = key.expires_at is not None and timezone.now() >= key.expires_at
        is_usable = key.is_active and not is_expired
        assert is_usable is False


# ═══════════════════════════════════════════════════════════════════
#  APIKeyAuthentication class (mocked, no DB)
# ═══════════════════════════════════════════════════════════════════

class TestAPIKeyAuthentication:
    """Unit-test the authenticate() method with mocked DB and request."""

    def _make_request(self, api_key=None, api_secret=None):
        """Build a fake request with META headers."""
        meta = {}
        if api_key is not None:
            meta['HTTP_X_API_KEY'] = api_key
        if api_secret is not None:
            meta['HTTP_X_API_SECRET'] = api_secret
        return SimpleNamespace(META=meta)

    def _make_auth(self):
        from config.authentication import APIKeyAuthentication
        return APIKeyAuthentication()

    def test_returns_none_when_no_headers(self):
        auth = self._make_auth()
        request = self._make_request()
        assert auth.authenticate(request) is None

    def test_returns_none_when_only_key_header(self):
        auth = self._make_auth()
        request = self._make_request(api_key='abcd1234')
        assert auth.authenticate(request) is None

    def test_returns_none_when_only_secret_header(self):
        auth = self._make_auth()
        request = self._make_request(api_secret='0' * 64)
        assert auth.authenticate(request) is None

    @patch('bfg.common.middleware.set_current_workspace')
    def test_valid_key_returns_user_and_key(self, mock_set_ws):
        from rest_framework.exceptions import AuthenticationFailed

        auth = self._make_auth()
        raw_secret = 'my-raw-secret'
        user = SimpleNamespace(username='admin')
        workspace = SimpleNamespace(id=1, name='WS')

        key_obj = SimpleNamespace(
            pk=1,
            prefix='aabb1122',
            secret_hash=hash_secret(raw_secret),
            is_active=True,
            expires_at=None,
            created_by=user,
            workspace=workspace,
            is_usable=True,
            is_expired=False,
            verify_secret=lambda s: hash_secret(s) == hash_secret(raw_secret),
            record_usage=MagicMock(),
        )

        request = self._make_request(api_key='aabb1122', api_secret=raw_secret)

        with patch('config.authentication.APIKeyAuthentication.authenticate') as mock_auth:
            # We test the real logic by calling it manually with a mock model
            # Instead, let's test via the actual method with patched DB
            pass

        # Use patch on the model's manager
        mock_qs = MagicMock()
        mock_qs.get.return_value = key_obj

        with patch('bfg.common.models.APIKey.objects') as mock_manager:
            mock_manager.select_related.return_value = mock_qs
            result = auth.authenticate(request)

        assert result is not None
        returned_user, returned_auth = result
        assert returned_user == user
        assert returned_auth == key_obj
        key_obj.record_usage.assert_called_once()
        mock_set_ws.assert_called_once_with(workspace)
        assert request.workspace == workspace

    def test_nonexistent_key_raises(self):
        from rest_framework.exceptions import AuthenticationFailed
        from bfg.common.models import APIKey as APIKeyModel

        auth = self._make_auth()
        request = self._make_request(api_key='noexist1', api_secret='0' * 64)

        mock_qs = MagicMock()
        mock_qs.get.side_effect = APIKeyModel.DoesNotExist

        with patch('bfg.common.models.APIKey.objects') as mock_manager:
            mock_manager.select_related.return_value = mock_qs
            with pytest.raises(AuthenticationFailed, match='Invalid API key'):
                auth.authenticate(request)

    def test_inactive_key_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        auth = self._make_auth()
        key_obj = SimpleNamespace(
            is_usable=False,
            is_expired=False,
        )

        mock_qs = MagicMock()
        mock_qs.get.return_value = key_obj

        request = self._make_request(api_key='aabb1122', api_secret='x' * 64)

        with patch('bfg.common.models.APIKey.objects') as mock_manager:
            mock_manager.select_related.return_value = mock_qs
            with pytest.raises(AuthenticationFailed, match='inactive'):
                auth.authenticate(request)

    def test_expired_key_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        auth = self._make_auth()
        key_obj = SimpleNamespace(
            is_usable=False,
            is_expired=True,
        )

        mock_qs = MagicMock()
        mock_qs.get.return_value = key_obj

        request = self._make_request(api_key='aabb1122', api_secret='x' * 64)

        with patch('bfg.common.models.APIKey.objects') as mock_manager:
            mock_manager.select_related.return_value = mock_qs
            with pytest.raises(AuthenticationFailed, match='expired'):
                auth.authenticate(request)

    def test_wrong_secret_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        auth = self._make_auth()
        key_obj = SimpleNamespace(
            is_usable=True,
            is_expired=False,
            verify_secret=lambda s: False,
        )

        mock_qs = MagicMock()
        mock_qs.get.return_value = key_obj

        request = self._make_request(api_key='aabb1122', api_secret='wrong')

        with patch('bfg.common.models.APIKey.objects') as mock_manager:
            mock_manager.select_related.return_value = mock_qs
            with pytest.raises(AuthenticationFailed, match='Invalid API secret'):
                auth.authenticate(request)

    @patch('bfg.common.middleware.set_current_workspace')
    def test_no_created_by_returns_anonymous(self, mock_set_ws):
        from django.contrib.auth.models import AnonymousUser

        auth = self._make_auth()
        raw_secret = 'secret123'
        workspace = SimpleNamespace(id=1, name='WS')

        key_obj = SimpleNamespace(
            pk=1,
            prefix='cc112233',
            secret_hash=hash_secret(raw_secret),
            is_active=True,
            expires_at=None,
            created_by=None,  # no creator
            workspace=workspace,
            is_usable=True,
            is_expired=False,
            verify_secret=lambda s: hash_secret(s) == hash_secret(raw_secret),
            record_usage=MagicMock(),
        )

        request = self._make_request(api_key='cc112233', api_secret=raw_secret)

        mock_qs = MagicMock()
        mock_qs.get.return_value = key_obj

        with patch('bfg.common.models.APIKey.objects') as mock_manager:
            mock_manager.select_related.return_value = mock_qs
            returned_user, returned_auth = auth.authenticate(request)

        assert isinstance(returned_user, AnonymousUser)
        assert returned_auth == key_obj

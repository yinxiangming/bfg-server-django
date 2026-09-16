# -*- coding: utf-8 -*-
"""JWT workspace claim security tests (Phase-0 PR-10).

Coverage:
* JWT claim minting (three workspace-source paths)
* Middleware JWT-first resolution
* Prod-mode: X-Workspace-ID ignored when Bearer present (security assertion)
* Non-prod / anonymous: X-Workspace-ID still honoured
* Anonymous + X-Forwarded-Host domain lookup still works
* switch-workspace: happy path, non-member 403, inactive workspace 404,
  default_workspace recorded for staff only
* Token refresh: keeps the refresh token's workspace while the user can still
  work there, otherwise falls back to the sign-in choice
* Session-auth non-member defence-in-depth 403
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from bfg.common.models import (
    Workspace,
    WorkspaceDomain,
    StaffMember,
    Customer,
    StaffRole,
)
from bfg.common.middleware import _decode_jwt_workspace_id, _thread_locals, set_current_workspace

User = get_user_model()
pytestmark = pytest.mark.django_db


# ─── helpers ─────────────────────────────────────────────────────────


def _mint_token(user, workspace_id=None):
    """Return a signed access-token string with optional workspace_id claim."""
    refresh = RefreshToken.for_user(user)
    if workspace_id is not None:
        refresh['workspace_id'] = workspace_id
    return str(refresh.access_token)


def _bearer(token):
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


def _join(user, workspace, membership='staff', **fields):
    """Give ``user`` an active staff membership or customer profile in ``workspace``."""
    if membership == 'customer':
        return Customer.objects.create(workspace=workspace, user=user, is_active=True, **fields)
    role, _ = StaffRole.objects.get_or_create(workspace=workspace, code='admin', defaults={'name': 'Admin'})
    return StaffMember.objects.create(workspace=workspace, user=user, role=role, is_active=True, **fields)


def _switch(user, workspace):
    """Switch ``user`` into ``workspace``; return the refresh token it hands back."""
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post('/api/v1/platform/switch-workspace/', {'workspace_id': workspace.id})
    assert resp.status_code == 200, resp.json()
    return resp.json()['refresh']


def _refresh(refresh):
    """Refresh as a client does once its access token expires.

    Returns the rotated refresh token and the workspace_id claims of the new
    access and refresh tokens.
    """
    resp = APIClient().post('/api/v1/auth/token/refresh/', {'refresh': refresh}, format='json')
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    access, rotated = AccessToken(data['access']), RefreshToken(data['refresh'])
    return data['refresh'], access.get('workspace_id'), rotated.get('workspace_id')


# ─── fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_thread():
    cache.clear()  # prevent LocMemCache bleed between tests
    set_current_workspace(None)
    yield
    set_current_workspace(None)


@pytest.fixture
def ws(db):
    return Workspace.objects.create(name='Alpha', slug='alpha', is_active=True)


@pytest.fixture
def ws2(db):
    return Workspace.objects.create(name='Beta', slug='beta', is_active=True)


@pytest.fixture
def user(db):
    return User.objects.create_user(username='tester', password='pass1234')


@pytest.fixture
def staff_user(db, ws):
    u = User.objects.create_user(username='staffer', password='pass1234', default_workspace=ws)
    role, _ = StaffRole.objects.get_or_create(workspace=ws, code='admin', defaults={'name': 'Admin'})
    StaffMember.objects.create(workspace=ws, user=u, role=role, is_active=True)
    return u


@pytest.fixture
def customer_user(db, ws):
    u = User.objects.create_user(username='buyer', password='pass1234')
    Customer.objects.create(workspace=ws, user=u, is_active=True)
    return u


@pytest.fixture
def rotating_refresh_tokens(monkeypatch):
    """Rotate and blacklist refresh tokens on use, as config/settings.py deploys them.

    Patched on the settings object config.serializers imported: override_settings
    would have simplejwt build a new one, which the serializer never sees.
    """
    from config import serializers
    monkeypatch.setattr(serializers.jwt_api_settings, 'ROTATE_REFRESH_TOKENS', True)
    monkeypatch.setattr(serializers.jwt_api_settings, 'BLACKLIST_AFTER_ROTATION', True)


# ─── JWT claim minting ───────────────────────────────────────────────


class TestJwtClaimMinting:
    def test_staff_member_gets_workspace_claim(self, staff_user, ws):
        from config.serializers import CustomTokenObtainPairSerializer
        refresh = CustomTokenObtainPairSerializer.get_token(staff_user)
        assert refresh['workspace_id'] == ws.id

    def test_customer_gets_workspace_claim(self, customer_user, ws):
        from config.serializers import CustomTokenObtainPairSerializer
        refresh = CustomTokenObtainPairSerializer.get_token(customer_user)
        assert refresh['workspace_id'] == ws.id

    def test_user_with_no_membership_gets_none_claim(self, user):
        from config.serializers import CustomTokenObtainPairSerializer
        refresh = CustomTokenObtainPairSerializer.get_token(user)
        assert refresh['workspace_id'] is None

    def test_default_workspace_preferred_when_staff_member_there(self, db):
        ws_default = Workspace.objects.create(name='Default', slug='default-ws', is_active=True)
        ws_other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
        u = User.objects.create_user(username='multi', password='pass', default_workspace=ws_default)
        role, _ = StaffRole.objects.get_or_create(workspace=ws_default, code='admin', defaults={'name': 'Admin'})
        StaffRole.objects.get_or_create(workspace=ws_other, code='admin', defaults={'name': 'Admin'})
        StaffMember.objects.create(workspace=ws_default, user=u, role=role, is_active=True)
        other_role, _ = StaffRole.objects.get_or_create(workspace=ws_other, code='admin', defaults={'name': 'Admin'})
        StaffMember.objects.create(workspace=ws_other, user=u, role=other_role, is_active=True)
        from config.serializers import CustomTokenObtainPairSerializer
        refresh = CustomTokenObtainPairSerializer.get_token(u)
        # default_workspace is ws_default and user is staff there → should be preferred
        assert refresh['workspace_id'] == ws_default.id

    @pytest.mark.parametrize('membership', ['staff', 'customer'])
    def test_membership_in_deactivated_workspace_does_not_hide_an_older_one(self, user, ws, ws2, membership):
        from config.serializers import CustomTokenObtainPairSerializer
        _join(user, ws, membership, created_at=timezone.now() - timedelta(days=1))
        _join(user, ws2, membership)
        ws2.is_active = False
        ws2.save()

        refresh = CustomTokenObtainPairSerializer.get_token(user)

        assert refresh['workspace_id'] == ws.id


# ─── _decode_jwt_workspace_id ────────────────────────────────────────


class TestDecodeJwtWorkspaceId:
    def test_extracts_workspace_id_from_access_token(self, ws, rf):
        token = _mint_token(User.objects.create_user('dec_user', 'x'), workspace_id=ws.id)
        request = rf.get('/', **_bearer(token))
        assert _decode_jwt_workspace_id(request) == (ws.id, True)

    def test_returns_none_for_missing_header(self, rf):
        request = rf.get('/')
        assert _decode_jwt_workspace_id(request) == (None, False)

    def test_returns_none_for_invalid_token(self, rf):
        request = rf.get('/', HTTP_AUTHORIZATION='Bearer not.a.token')
        # Invalid token → token_valid=False so middleware can fall back to domain
        assert _decode_jwt_workspace_id(request) == (None, False)

    def test_returns_none_when_no_workspace_claim(self, rf):
        u = User.objects.create_user('no_claim', 'x')
        # Token without workspace_id claim
        refresh = RefreshToken.for_user(u)
        token = str(refresh.access_token)
        request = rf.get('/', **_bearer(token))
        # workspace_id key absent but token is valid → (None, True)
        assert _decode_jwt_workspace_id(request) == (None, True)


# ─── Middleware JWT-first resolution ─────────────────────────────────


class TestMiddlewareJwtResolution:
    def test_workspace_collection_supports_first_tenant_bootstrap(self, user):
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get('/api/v1/workspaces/')

        assert response.status_code == 200
        assert response.json() == []

    def test_jwt_claim_resolves_workspace(self, staff_user, ws):
        token = _mint_token(staff_user, workspace_id=ws.id)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            **_bearer(token),
        )
        # Middleware resolved workspace from JWT claim → request gets through (not 400)
        assert response.status_code != 400

    def test_jwt_with_unknown_workspace_id_rejected(self, user):
        token = _mint_token(user, workspace_id=999999)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            **_bearer(token),
        )
        assert response.status_code == 400
        assert response.json()['code'] == 'workspace_required'

    def test_jwt_claim_takes_priority_over_header(self, staff_user, ws, ws2):
        """JWT workspace wins even when a different X-Workspace-ID header is present."""
        token = _mint_token(staff_user, workspace_id=ws.id)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws2.id),
            **_bearer(token),
        )
        # Request resolves (ws is valid) even though ws2 was in the header
        assert response.status_code != 400


# ─── Security: prod mode ignores X-Workspace-ID for authenticated requests ───


class TestProdModeHeaderSpoofing:
    @override_settings(IS_PROD=True)
    def test_prod_auth_request_ignores_x_workspace_id_header(self, user, ws):
        """Key security assertion: in prod, bearer + X-Workspace-ID → header ignored,
        workspace must come from JWT claim."""
        # Token has NO workspace_id claim; header points to ws
        refresh = RefreshToken.for_user(user)
        token = str(refresh.access_token)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws.id),
            **_bearer(token),
        )
        # JWT has no claim → domain lookup also fails → 400 (header was ignored)
        assert response.status_code == 400
        assert response.json()['code'] == 'workspace_required'

    @override_settings(IS_PROD=True)
    def test_prod_with_jwt_claim_resolves_correctly(self, staff_user, ws):
        token = _mint_token(staff_user, workspace_id=ws.id)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            **_bearer(token),
        )
        assert response.status_code != 400

    @override_settings(IS_PROD=True)
    def test_prod_jwt_claim_wins_over_x_workspace_id(self, staff_user, ws, ws2):
        """In prod: JWT claim=ws beats a forged X-Workspace-ID=ws2 (PR-12 assertion)."""
        token = _mint_token(staff_user, workspace_id=ws.id)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws2.id),
            **_bearer(token),
        )
        # ws resolved via JWT claim; ws2 header is ignored
        assert response.status_code != 400

    @override_settings(IS_PROD=True)
    def test_prod_bearer_no_claim_rejected_before_domain_lookup(self, user, ws):
        """In prod: Bearer token without workspace_id claim → 400, no domain fallback (PR-12)."""
        WorkspaceDomain.objects.create(
            workspace=ws,
            hostname='testserver',
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        )
        refresh = RefreshToken.for_user(user)
        token = str(refresh.access_token)  # no workspace_id claim
        response = Client().get(
            '/api/v1/__strict_probe__/',
            **_bearer(token),
        )
        # Domain 'testserver' exists but must not be used for prod+authenticated+no-claim
        assert response.status_code == 400
        assert response.json()['code'] == 'workspace_required'

    @override_settings(IS_PROD=True)
    def test_prod_invalid_bearer_falls_back_to_domain(self, ws, db):
        """Expired/invalid Bearer token must not short-circuit domain resolution.

        Regression test: previously, any Bearer header in prod would block the
        domain fallback, causing public storefront endpoints to 400 when the
        client's access token expired. An invalid token is semantically
        anonymous (DRF auth will reject it at the view layer), so the
        middleware should fall through to X-Forwarded-Host domain lookup.
        """
        WorkspaceDomain.objects.create(
            workspace=ws,
            hostname='shop.example.com',
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        )
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_FORWARDED_HOST='shop.example.com',
            HTTP_AUTHORIZATION='Bearer not.a.valid.token',
        )
        # Invalid JWT → treated as anonymous → domain resolves → not 400
        assert response.status_code != 400

    @override_settings(IS_PROD=True)
    def test_prod_invalid_bearer_without_domain_still_400(self, ws):
        """Invalid Bearer + no resolvable domain still yields 400 (no silent fallback)."""
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_AUTHORIZATION='Bearer not.a.valid.token',
        )
        assert response.status_code == 400
        assert response.json()['code'] == 'workspace_required'

    def test_non_prod_auth_request_honours_x_workspace_id(self, user, ws):
        """IS_PROD=False (test default): X-Workspace-ID header still accepted."""
        refresh = RefreshToken.for_user(user)
        token = str(refresh.access_token)
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws.id),
            **_bearer(token),
        )
        # Header resolves ws → not 400
        assert response.status_code != 400

    def test_anonymous_x_workspace_id_always_honoured(self, ws):
        """Anonymous requests (no Bearer) always use X-Workspace-ID regardless of IS_PROD."""
        with override_settings(IS_PROD=True):
            response = Client().get(
                '/api/v1/__strict_probe__/',
                HTTP_X_WORKSPACE_ID=str(ws.id),
            )
            assert response.status_code != 400


# ─── Domain-based resolution (storefront / anonymous) ────────────────


class TestDomainResolution:
    def test_x_forwarded_host_resolves_workspace(self, ws, db):
        WorkspaceDomain.objects.create(
            workspace=ws,
            hostname='shop.example.com',
            kind=WorkspaceDomain.KIND_CUSTOM,
            verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        )
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_FORWARDED_HOST='shop.example.com',
        )
        assert response.status_code != 400

    def test_unknown_domain_returns_400(self, ws):
        response = Client().get(
            '/api/v1/__strict_probe__/',
            HTTP_X_FORWARDED_HOST='unknown.example.com',
        )
        assert response.status_code == 400


# ─── switch-workspace endpoint ───────────────────────────────────────


class TestSwitchWorkspace:
    def test_happy_path_returns_new_tokens(self, staff_user, ws):
        client = APIClient()
        client.force_authenticate(user=staff_user)
        resp = client.post('/api/v1/platform/switch-workspace/', {'workspace_id': ws.id})
        assert resp.status_code == 200
        data = resp.json()
        assert 'access' in data
        assert 'refresh' in data
        assert data['workspace']['id'] == ws.id
        assert data['workspace']['slug'] == ws.slug

    def test_happy_path_token_contains_workspace_claim(self, staff_user, ws):
        client = APIClient()
        client.force_authenticate(user=staff_user)
        resp = client.post('/api/v1/platform/switch-workspace/', {'workspace_id': ws.id})
        assert resp.status_code == 200
        # Decode the returned access token and verify workspace_id claim
        from rest_framework_simplejwt.backends import TokenBackend
        from django.conf import settings as _s
        backend = TokenBackend(
            algorithm=getattr(_s, 'SIMPLE_JWT', {}).get('ALGORITHM', 'HS256'),
            signing_key=getattr(_s, 'SIMPLE_JWT', {}).get('SIGNING_KEY', _s.SECRET_KEY),
        )
        payload = backend.decode(resp.json()['access'], verify=True)
        assert payload['workspace_id'] == ws.id

    def test_non_member_gets_403(self, user, ws):
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post('/api/v1/platform/switch-workspace/', {'workspace_id': ws.id})
        assert resp.status_code == 403
        assert resp.json()['code'] == 'workspace_access_denied'

    def test_inactive_workspace_gets_404(self, staff_user, ws):
        ws.is_active = False
        ws.save()
        client = APIClient()
        client.force_authenticate(user=staff_user)
        resp = client.post('/api/v1/platform/switch-workspace/', {'workspace_id': ws.id})
        assert resp.status_code == 404

    def test_missing_workspace_id_gets_400(self, staff_user):
        client = APIClient()
        client.force_authenticate(user=staff_user)
        resp = client.post('/api/v1/platform/switch-workspace/', {})
        assert resp.status_code == 400

    def test_unauthenticated_gets_rejected(self, ws):
        resp = APIClient().post('/api/v1/platform/switch-workspace/', {'workspace_id': ws.id})
        assert resp.status_code in (401, 403)

    def test_customer_can_switch(self, customer_user, ws):
        client = APIClient()
        client.force_authenticate(user=customer_user)
        resp = client.post('/api/v1/platform/switch-workspace/', {'workspace_id': ws.id})
        assert resp.status_code == 200

    def test_staff_switch_becomes_default_workspace(self, staff_user, ws2):
        from config.serializers import CustomTokenObtainPairSerializer
        _join(staff_user, ws2)

        _switch(staff_user, ws2)

        staff_user.refresh_from_db()
        assert staff_user.default_workspace_id == ws2.id
        # ...which is where the next sign-in lands
        assert CustomTokenObtainPairSerializer.get_token(staff_user)['workspace_id'] == ws2.id

    def test_customer_switch_leaves_default_workspace_alone(self, staff_user, ws, ws2):
        _join(staff_user, ws2, 'customer')

        _switch(staff_user, ws2)

        staff_user.refresh_from_db()
        assert staff_user.default_workspace_id == ws.id


# ─── Token refresh keeps the switched workspace ──────────────────────


@pytest.mark.usefixtures('rotating_refresh_tokens')
class TestTokenRefreshWorkspace:
    @pytest.mark.parametrize('membership', ['staff', 'customer'])
    def test_switched_workspace_survives_consecutive_refreshes(self, staff_user, ws2, membership):
        # A customer switch leaves default_workspace on ws, so only the token's own claim keeps ws2.
        _join(staff_user, ws2, membership)
        refresh = _switch(staff_user, ws2)

        for _ in range(2):
            refresh, access_ws, refresh_ws = _refresh(refresh)
            assert (access_ws, refresh_ws) == (ws2.id, ws2.id)

    @pytest.mark.parametrize('lost', ['membership_revoked', 'workspace_deactivated'])
    def test_unusable_workspace_falls_back_to_sign_in_choice(self, staff_user, ws, ws2, lost):
        _join(staff_user, ws2)
        refresh = _switch(staff_user, ws2)
        if lost == 'membership_revoked':
            StaffMember.all_objects.filter(workspace=ws2, user=staff_user).update(is_active=False)
        else:
            ws2.is_active = False
            ws2.save()

        _, access_ws, refresh_ws = _refresh(refresh)

        # The switch made ws2 default_workspace, and it holds the newest membership:
        # neither may keep the session there.
        assert (access_ws, refresh_ws) == (ws.id, ws.id)

    def test_token_without_workspace_claim_gets_sign_in_choice(self, staff_user, ws):
        # As minted before tokens carried the claim.
        _, access_ws, refresh_ws = _refresh(str(RefreshToken.for_user(staff_user)))

        assert (access_ws, refresh_ws) == (ws.id, ws.id)


# ─── Defence-in-depth: session-auth non-member → 403 ────────────────


class TestSessionAuthNonMemberDefence:
    def test_session_user_without_membership_gets_403(self, user, ws):
        """Session-authenticated user with no membership in the resolved workspace → 403."""
        c = Client()
        c.force_login(user)
        response = c.get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        assert response.status_code == 403
        assert response.json()['code'] == 'workspace_access_denied'

    def test_session_staff_member_passes(self, staff_user, ws):
        c = Client()
        c.force_login(staff_user)
        response = c.get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        assert response.status_code != 403

    def test_session_customer_passes(self, customer_user, ws):
        c = Client()
        c.force_login(customer_user)
        response = c.get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        assert response.status_code != 403

    def test_superuser_bypasses_membership_check(self, db, ws):
        su = User.objects.create_superuser('super', 'super@example.com', 'pass1234')
        c = Client()
        c.force_login(su)
        response = c.get(
            '/api/v1/__strict_probe__/',
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        assert response.status_code != 403

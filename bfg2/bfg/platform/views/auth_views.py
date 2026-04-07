# -*- coding: utf-8 -*-
"""
Authentication ViewSet for cross-instance auth:
  - Token Exchange (Platform JWT → Workspace JWT)
  - SSO check + provider callbacks

Supports embedded and standalone modes:
  - Embedded: token exchange returns the same JWT (no cross-instance call)
  - Standalone: token exchange calls Workspace Server to provision user + get JWT
"""
import requests as http_requests

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.apps import apps

from bfg.platform.utils import is_embedded_mode


class AuthViewSet(viewsets.ViewSet):
    """
    Platform auth actions.

    POST /api/v1/platform/auth/token-exchange/
    GET  /api/v1/platform/auth/sso-check/
    GET  /api/v1/platform/auth/google-callback/
    GET  /api/v1/platform/auth/azure-callback/
    """

    def get_permissions(self):
        if self.action in ('token_exchange', 'sso_start'):
            return [IsAuthenticated()]
        return [AllowAny()]

    @action(detail=False, methods=['post'], url_path='token-exchange')
    def token_exchange(self, request):
        """
        POST /api/v1/platform/auth/token-exchange/
        Exchange Platform JWT for a Workspace JWT.
        Body: { "workspace_id": "ws-slug-or-id" }

        Embedded mode: verifies StaffMember access, returns the existing JWT
        (no cross-instance call needed since everything is in the same DB).

        Standalone mode: calls Workspace Server's provision-user API.
        """
        workspace_id = request.data.get('workspace_id')
        if not workspace_id:
            return Response(
                {'error': 'workspace_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if is_embedded_mode():
            return self._token_exchange_embedded(request, workspace_id)
        else:
            return self._token_exchange_standalone(request, workspace_id)

    def _token_exchange_embedded(self, request, workspace_id):
        """Embedded: verify StaffMember access, return existing token (same DB)."""
        StaffMember = apps.get_model('common', 'StaffMember')
        Workspace = apps.get_model('common', 'Workspace')

        # Find workspace by slug or id
        try:
            workspace = Workspace.objects.get(slug=workspace_id)
        except Workspace.DoesNotExist:
            try:
                workspace = Workspace.objects.get(id=workspace_id)
            except (Workspace.DoesNotExist, ValueError):
                return Response(
                    {'error': 'Workspace not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Verify user has access
        if not StaffMember.objects.filter(
            user=request.user, workspace=workspace, is_active=True
        ).exists():
            return Response(
                {'error': 'No access to this workspace'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # In embedded mode the same JWT works for all workspaces.
        # Re-issue a fresh token scoped to this user (same as login token).
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(request.user)

        return Response({
            'workspace_token': str(refresh.access_token),
            'workspace_url': None,  # same server
            'workspace_frontend_url': None,  # same frontend
            'workspace_server_id': workspace.id,
            'workspace': {
                'id': workspace.id,
                'uuid': str(workspace.uuid) if getattr(workspace, 'uuid', None) else None,
                'name': workspace.name,
                'slug': workspace.slug,
            },
            'embedded': True,
        })

    def _token_exchange_standalone(self, request, workspace_id):
        """Standalone: call Workspace Server to provision user and get JWT."""
        PlatformMembership = apps.get_model('platform', 'PlatformMembership')

        # Try by workspace slug, then by workspace id (numeric)
        membership = PlatformMembership.objects.filter(
            user=request.user,
            profile__workspace__slug=workspace_id,
            is_active=True,
        ).select_related('profile', 'profile__workspace', 'profile__cluster').first()

        if not membership:
            try:
                ws_pk = int(workspace_id)
                membership = PlatformMembership.objects.filter(
                    user=request.user,
                    profile__workspace_id=ws_pk,
                    is_active=True,
                ).select_related('profile', 'profile__workspace', 'profile__cluster').first()
            except (ValueError, TypeError):
                pass  # workspace_id is not numeric, skip id lookup

        if not membership:
            return Response(
                {'error': 'No access to this workspace'},
                status=status.HTTP_403_FORBIDDEN,
            )

        profile = membership.profile
        workspace = profile.workspace

        from django.conf import settings

        platform_api_key = getattr(settings, 'PLATFORM_API_KEY', 'local-dev-key')

        workspace_api_url = (
            profile.cluster.api_base_url
            if profile and profile.cluster
            else f'https://{workspace.domain}'
        )

        # Override workspace URL for local development if needed
        if settings.DEBUG and ('localhost' in (workspace.domain or '') or not workspace.domain):
            workspace_api_url = 'http://localhost:8000'

        try:
            resp = http_requests.post(
                f'{workspace_api_url}/api/v1/internal/auth/provision-user/',
                json={
                    'platform_user_id': str(request.user.id),
                    'email': request.user.email,
                    'name': request.user.get_full_name(),
                    'role': membership.role,
                    'workspace_slug': workspace.slug,
                },
                headers={'Authorization': f'Bearer {platform_api_key}'},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as e:
            return Response(
                {'error': f'Token exchange failed: {e}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        resp_data = resp.json()

        # Store remote_workspace_uuid if returned and not yet set
        remote_uuid = resp_data.get('workspace_uuid')
        if remote_uuid and not profile.remote_workspace_uuid:
            profile.remote_workspace_uuid = remote_uuid
            profile.save(update_fields=['remote_workspace_uuid'])

        # Resolve workspace frontend URL from cluster, falling back to env/settings
        workspace_frontend_url = (
            profile.cluster.frontend_base_url
            if profile and profile.cluster and getattr(profile.cluster, 'frontend_base_url', None)
            else getattr(settings, 'WORKSPACE_FRONTEND_URL', '')
        )

        return Response({
            'workspace_token': resp_data.get('token'),
            'workspace_url': workspace_api_url,
            'workspace_frontend_url': workspace_frontend_url,
            'workspace_server_id': resp_data.get('workspace_id'),
            'workspace': {
                'id': workspace.id,
                'uuid': str(workspace.uuid) if getattr(workspace, 'uuid', None) else None,
                'name': workspace.name,
                'slug': workspace.slug,
            },
            'embedded': False,
        })

    # ── SSO Code Bridge ────────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='sso/start')
    def sso_start(self, request):
        """
        POST /api/v1/platform/auth/sso/start/
        Generate a one-time SSO code and return the redirect URL to the
        target workspace domain.

        Body: { "workspace_id": "slug-or-id", "next": "/admin", "domain": "" }
        Returns: { "redirect_url": "https://domain/admin/sso?code=xxx" }
        """
        workspace_id = request.data.get('workspace_id')
        if not workspace_id:
            return Response(
                {'error': 'workspace_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        next_url = request.data.get('next', '/admin')
        override_domain = request.data.get('domain', '').strip()

        Workspace = apps.get_model('common', 'Workspace')

        # Resolve workspace
        try:
            workspace = Workspace.objects.get(slug=workspace_id)
        except Workspace.DoesNotExist:
            try:
                workspace = Workspace.objects.get(id=workspace_id)
            except (Workspace.DoesNotExist, ValueError):
                return Response(
                    {'error': 'Workspace not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Verify access (embedded: StaffMember, standalone: PlatformMembership)
        if is_embedded_mode():
            StaffMember = apps.get_model('common', 'StaffMember')
            has_access = StaffMember.objects.filter(
                user=request.user, workspace=workspace, is_active=True,
            ).exists()
        else:
            PlatformMembership = apps.get_model('platform', 'PlatformMembership')
            has_access = PlatformMembership.objects.filter(
                user=request.user,
                profile__workspace=workspace,
                is_active=True,
            ).exists()

        if not has_access:
            return Response(
                {'error': 'No access to this workspace'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Resolve target domain
        target_domain = override_domain
        if not target_domain:
            profile = getattr(workspace, 'platform_profile', None)
            custom = (str(profile.custom_domain).strip() if profile and profile.custom_domain else '')
            if custom:
                target_domain = custom
            elif profile and profile.cluster and getattr(profile.cluster, 'frontend_base_url', None):
                target_domain = (profile.cluster.frontend_base_url or '').strip()
            else:
                from django.conf import settings as django_settings
                target_domain = (
                    getattr(django_settings, 'WORKSPACE_FRONTEND_URL', '')
                    or getattr(django_settings, 'FRONTEND_URL', '')
                )
                if isinstance(target_domain, str):
                    target_domain = target_domain.strip()

        if not target_domain:
            return Response(
                {'error': 'Cannot determine workspace frontend URL'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Ensure scheme
        if not target_domain.startswith(('http://', 'https://')):
            target_domain = f'https://{target_domain}'
        target_domain = target_domain.rstrip('/')

        # Create SSO code
        PlatformSSOCode = apps.get_model('platform', 'PlatformSSOCode')
        client_ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() \
            or request.META.get('REMOTE_ADDR')

        sso_code = PlatformSSOCode(
            workspace=workspace,
            user=request.user,
            next_url=next_url,
            redirect_domain=target_domain,
            created_by_ip=client_ip or None,
        )
        sso_code.save()

        redirect_url = f'{target_domain}/admin/sso?code={sso_code.code}'
        if next_url and next_url != '/admin':
            import urllib.parse
            redirect_url += f'&next={urllib.parse.quote(next_url)}'

        return Response({'redirect_url': redirect_url})

    @action(detail=False, methods=['post'], url_path='sso/exchange')
    def sso_exchange(self, request):
        """
        POST /api/v1/platform/auth/sso/exchange/
        Exchange a one-time SSO code for workspace JWT tokens.

        Body: { "code": "xxxxx" }
        Returns: { "access": "...", "refresh": "...", "workspace": {...}, "next": "/admin" }
        """
        code_value = request.data.get('code', '').strip()
        if not code_value:
            return Response(
                {'error': 'code is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        PlatformSSOCode = apps.get_model('platform', 'PlatformSSOCode')

        try:
            sso_code = PlatformSSOCode.objects.select_related(
                'workspace', 'user',
            ).get(code=code_value)
        except PlatformSSOCode.DoesNotExist:
            return Response(
                {'error': 'Invalid SSO code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if sso_code.is_used:
            return Response(
                {'error': 'SSO code has already been used'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if sso_code.is_expired:
            return Response(
                {'error': 'SSO code has expired'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark used immediately to prevent replay
        sso_code.mark_used()

        workspace = sso_code.workspace
        user = sso_code.user

        # Issue JWT — reuse the same logic as token_exchange
        if is_embedded_mode():
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)

            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'workspace': {
                    'id': workspace.id,
                    'uuid': str(workspace.uuid) if getattr(workspace, 'uuid', None) else None,
                    'name': workspace.name,
                    'slug': workspace.slug,
                },
                'next': sso_code.next_url or '/admin',
                'embedded': True,
            })
        else:
            # Standalone: call workspace server to provision user + get JWT
            profile = getattr(workspace, 'platform_profile', None)
            if not profile or not profile.cluster:
                return Response(
                    {'error': 'Workspace cluster not configured'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            from django.conf import settings as django_settings
            platform_api_key = getattr(django_settings, 'PLATFORM_API_KEY', 'local-dev-key')

            workspace_api_url = profile.cluster.api_base_url
            if django_settings.DEBUG and ('localhost' in (workspace.domain or '') or not workspace.domain):
                workspace_api_url = 'http://localhost:8000'

            # Resolve role from PlatformMembership
            PlatformMembership = apps.get_model('platform', 'PlatformMembership')
            membership = PlatformMembership.objects.filter(
                user=user, profile=profile, is_active=True,
            ).first()
            role = membership.role if membership else 'staff'

            try:
                resp = http_requests.post(
                    f'{workspace_api_url}/api/v1/internal/auth/provision-user/',
                    json={
                        'platform_user_id': str(user.id),
                        'email': user.email,
                        'name': user.get_full_name(),
                        'role': role,
                        'workspace_slug': workspace.slug,
                    },
                    headers={'Authorization': f'Bearer {platform_api_key}'},
                    timeout=10,
                )
                resp.raise_for_status()
            except Exception as e:
                return Response(
                    {'error': f'Token exchange failed: {e}'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            resp_data = resp.json()

            workspace_frontend_url = (
                profile.cluster.frontend_base_url
                if getattr(profile.cluster, 'frontend_base_url', None)
                else getattr(django_settings, 'WORKSPACE_FRONTEND_URL', '')
            )

            return Response({
                'access': resp_data.get('token'),
                'refresh': resp_data.get('refresh', ''),
                'workspace_url': workspace_api_url,
                'workspace_frontend_url': workspace_frontend_url,
                'workspace': {
                    'id': workspace.id,
                    'uuid': str(workspace.uuid) if getattr(workspace, 'uuid', None) else None,
                    'name': workspace.name,
                    'slug': workspace.slug,
                },
                'next': sso_code.next_url or '/admin',
                'embedded': False,
            })

    @action(detail=False, methods=['get'], url_path='sso-check')
    def sso_check(self, request):
        """
        GET /api/v1/platform/auth/sso-check/?domain=acme.com
        See: docs/platform/00-architecture-overview.md §12
        """
        domain = request.query_params.get('domain', '').strip().lower()
        if not domain:
            return Response({'sso_enabled': False})

        WorkspaceSSOConfig = apps.get_model('platform', 'WorkspaceSSOConfig')
        config = WorkspaceSSOConfig.objects.filter(
            email_domain=domain, is_active=True
        ).first()

        if not config:
            return Response({'sso_enabled': False})

        return Response({
            'sso_enabled': True,
            'protocol': config.protocol,
            'enforce_sso': config.enforce_sso,
            'redirect_url': _build_sso_redirect(config, request),
        })

    @action(detail=False, methods=['get'], url_path='google-callback')
    def google_callback(self, request):
        """GET /api/v1/platform/auth/google-callback/?code=xxx&state=xxx"""
        raise NotImplementedError('Google SSO — implement with google-auth library')

    @action(detail=False, methods=['get'], url_path='azure-callback')
    def azure_callback(self, request):
        """GET /api/v1/platform/auth/azure-callback/?code=xxx&state=xxx"""
        raise NotImplementedError('Azure SSO — implement with msal library')


# ── Internal API (Workspace → Platform) ──────────────────────────────────────

class InternalAuthViewSet(viewsets.ViewSet):
    """
    Internal-only endpoints called by Workspace instances (standalone mode).
    Authenticated via X-Platform-API-Key header (IsPlatformAPIKey permission).

    POST /api/v1/platform/internal/provision-user/
    """
    from bfg.platform.permissions import IsPlatformAPIKey
    permission_classes = [IsPlatformAPIKey]

    @action(detail=False, methods=['post'], url_path='provision-user')
    def provision_user(self, request):
        """
        POST /api/v1/platform/internal/provision-user/
        Called by a Workspace to sync a user and get a JWT.
        Body: { platform_user_id, email, name, role }

        NOTE: This endpoint lives on the Platform side for reference.
        The *actual* provision-user that Workspace instances expose is in
        the BFG core or a workspace-side extension (not here).
        """
        raise NotImplementedError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_sso_redirect(config, request) -> str:
    """Build the IdP redirect URL based on SSO protocol."""
    import urllib.parse
    base = request.build_absolute_uri('/api/v1/platform/auth')
    state = f'workspace={config.workspace_id}'

    if config.protocol == 'google_oauth2':
        params = {
            'client_id': config.client_id,
            'redirect_uri': f'{base}/google-callback/',
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state,
            'hd': config.email_domain,
        }
        return f'https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}'

    if config.protocol == 'azure_oidc':
        tenant = config.tenant_id or 'common'
        params = {
            'client_id': config.client_id,
            'redirect_uri': f'{base}/azure-callback/',
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state,
        }
        return f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}'

    if config.protocol == 'oidc':
        return config.oidc_discovery_url or ''

    if config.protocol == 'saml2':
        return config.saml_metadata_url or ''

    return ''


# ── Public SSO check standalone view (kept for SSOConfigViewSet delegation) ──

class SSOCheckView:
    """Thin wrapper used by SSOConfigViewSet.check delegation."""
    def get(self, request):
        domain = request.query_params.get('domain', '').strip().lower()
        if not domain:
            return Response({'sso_enabled': False})
        WorkspaceSSOConfig = apps.get_model('platform', 'WorkspaceSSOConfig')
        config = WorkspaceSSOConfig.objects.filter(email_domain=domain, is_active=True).first()
        if not config:
            return Response({'sso_enabled': False})
        return Response({
            'sso_enabled': True,
            'protocol': config.protocol,
            'enforce_sso': config.enforce_sso,
            'redirect_url': _build_sso_redirect(config, request),
        })


class GoogleSSOCallbackView:
    def get(self, request):
        raise NotImplementedError('Google SSO — implement with google-auth library')


class AzureSSOCallbackView:
    def get(self, request):
        raise NotImplementedError('Azure SSO — implement with msal library')

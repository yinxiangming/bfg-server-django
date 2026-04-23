# -*- coding: utf-8 -*-
"""Multi-tenancy middleware for BFG2.

Phase-0 PR-04+PR-09: strict workspace binding.

Every request must resolve to a workspace via header or domain; the
legacy "first active workspace" fallback is gone because it silently
bound unauthenticated or header-less requests to whichever tenant
happened to be first in the DB — a severe cross-tenant leak.
"""

import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

from .models import (
    Workspace,
    WorkspaceDomain,
    get_workspace_domain_cache_key,
    normalize_hostname,
)
from .storefront_cache import invalidate_storefront_config_cache

try:
    from rest_framework_simplejwt.backends import TokenBackend
    from rest_framework_simplejwt.exceptions import TokenBackendError
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False

logger = logging.getLogger(__name__)

# Thread-local storage for current workspace — read by TenantScopedManager
# (and by any other code that needs the request-scoped workspace without
# plumbing ``request`` through its call chain).
_thread_locals = threading.local()

# Cache timeout for workspace lookups (10 minutes).
WORKSPACE_CACHE_TIMEOUT = 600

# ─── Request paths that operate outside any workspace context ─────────
# Hitting one of these bypasses the strict workspace requirement.
# These are either (a) identity/platform endpoints where the caller has
# no tenant yet, or (b) infrastructural (schema, health, webhook).
PUBLIC_PATHS = (
    '/api/v1/auth/',
    '/api/v1/platform/',
    '/api/v1/internal/',
    '/api/v1/health/',
    '/api/v1/invitations/preview/',
    '/api/v1/invitations/accept/',
    '/api/schema/',
    '/api/docs/',
    '/api/redoc/',
    '/admin/',
    '/.well-known/',
    '/api/v1/stripe/webhook/',
)

# Auth headers that carry enough information for the *view layer* to
# resolve the workspace (e.g. an API key bound to a specific workspace).
# When one of these is present we let the request pass the middleware
# check and let DRF's authentication classes populate ``request.workspace``.
WORKSPACE_DELEGATING_HEADERS = ('X-API-Key',)

# Response code emitted for strict-mode rejection. Kept as a module
# constant so both the middleware and its tests reference the same
# value (see tests/tenant_isolation/test_middleware_strict.py).
MISSING_WORKSPACE_RESPONSE = {
    'detail': (
        'Workspace required. Provide an X-Workspace-ID header or '
        'access the API via a workspace-mapped domain.'
    ),
    'code': 'workspace_required',
}


def get_current_workspace():
    """Get the request-scoped workspace from thread-local storage."""
    return getattr(_thread_locals, 'workspace', None)


def set_current_workspace(workspace):
    """Set the request-scoped workspace in thread-local storage."""
    if workspace is None:
        if hasattr(_thread_locals, 'workspace'):
            del _thread_locals.workspace
        return
    _thread_locals.workspace = workspace


def _get_workspace_by_domain(hostname):
    """Resolve a workspace by exact WorkspaceDomain match (cached)."""
    normalized = normalize_hostname(hostname)
    if not normalized:
        return None

    cache_key = get_workspace_domain_cache_key(normalized)
    workspace = cache.get(cache_key)
    if workspace is not None:
        return workspace

    try:
        domain = (
            WorkspaceDomain.objects
            .filter(hostname=normalized, workspace__is_active=True)
            .select_related('workspace')
            .first()
        )
        workspace = domain.workspace if domain and domain.workspace_id else None
        cache.set(cache_key, workspace, WORKSPACE_CACHE_TIMEOUT)
        return workspace
    except Exception as exc:  # noqa: BLE001 — log and fall through
        logger.error("Error resolving workspace for domain %s: %s", normalized, exc)
        cache.set(cache_key, None, WORKSPACE_CACHE_TIMEOUT)
        return None


def _get_workspace_by_id(workspace_id):
    """Resolve a workspace by numeric ID (cached)."""
    try:
        workspace_id = int(workspace_id)
    except (ValueError, TypeError):
        return None

    cache_key = f'workspace:id:{workspace_id}'
    workspace = cache.get(cache_key)
    if workspace is not None:
        if workspace and workspace.is_active:
            return workspace
        cache.delete(cache_key)
        return None

    try:
        workspace = Workspace.objects.get(id=workspace_id, is_active=True)
        cache.set(cache_key, workspace, WORKSPACE_CACHE_TIMEOUT)
        return workspace
    except Workspace.DoesNotExist:
        cache.set(cache_key, None, WORKSPACE_CACHE_TIMEOUT)
        return None


def invalidate_workspace_cache(workspace):
    """Drop every cache key tied to ``workspace``.

    Call this from post-save hooks on Workspace or WorkspaceDomain so
    the cached resolutions don't serve stale mappings.
    """
    if not workspace:
        return
    for hostname in workspace.domains.values_list('hostname', flat=True):
        if hostname:
            cache.delete(get_workspace_domain_cache_key(hostname))
    cache.delete(f'workspace:id:{workspace.id}')
    cache.delete(f'workspace:frontend-base-url:{workspace.id}')
    invalidate_storefront_config_cache(workspace.id)


def _hydrate_workspace_access(request, workspace):
    """Populate ``request.is_staff_member`` / ``request.is_customer``."""
    request.is_staff_member = False
    request.is_customer = False

    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False) or not workspace:
        return

    if getattr(user, 'is_superuser', False) and getattr(
        settings, 'BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS', True
    ):
        request.is_staff_member = True
        return

    from bfg.common.models import StaffMember, Customer  # local to avoid circular

    cache_key = f"user_ws_access:{user.id}:{workspace.id}"
    access_status = cache.get(cache_key)

    if access_status is None:
        is_staff = StaffMember.objects.filter(
            workspace=workspace, user=user, is_active=True,
        ).exists()
        is_customer = Customer.objects.filter(
            workspace=workspace, user=user, is_active=True,
        ).exists()
        access_status = {'is_staff_member': is_staff, 'is_customer': is_customer}
        cache.set(cache_key, access_status, WORKSPACE_CACHE_TIMEOUT)

    request.is_staff_member = bool(access_status.get('is_staff_member', False))
    request.is_customer = bool(access_status.get('is_customer', False))


WORKSPACE_ACCESS_DENIED_RESPONSE = {
    'detail': 'You are not a member of this workspace.',
    'code': 'workspace_access_denied',
}


def _decode_jwt_workspace_id(request):
    """Extract workspace_id from Bearer JWT claim without full DRF auth stack.

    Returns ``(workspace_id, token_valid)``:

    - ``(int, True)`` — JWT decoded successfully and carried a workspace_id claim
    - ``(None, True)`` — JWT decoded successfully but had no workspace_id claim
    - ``(None, False)`` — no Bearer header, or JWT present but invalid/expired

    Callers use ``token_valid`` to tell "authenticated request with no claim"
    (must be rejected in prod to prevent cross-tenant via header/domain spoofing)
    apart from "invalid/expired token" (caller is effectively anonymous — DRF
    auth will reject the token at the view layer, so falling through to domain
    resolution is safe and avoids breaking public endpoints like storefront).
    """
    if not _JWT_AVAILABLE:
        return None, False
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None, False
    raw_token = auth_header[len('Bearer '):]
    try:
        backend = TokenBackend(
            algorithm=getattr(settings, 'SIMPLE_JWT', {}).get('ALGORITHM', 'HS256'),
            signing_key=getattr(settings, 'SIMPLE_JWT', {}).get('SIGNING_KEY', settings.SECRET_KEY),
        )
        payload = backend.decode(raw_token, verify=True)
        ws_id = payload.get('workspace_id')
        return (int(ws_id) if ws_id is not None else None), True
    except (TokenBackendError, ValueError, TypeError):
        return None, False


class WorkspaceMiddleware:
    """Bind every request to exactly one workspace.

    Resolution order (PR-10):

    1. JWT claim ``workspace_id`` (Bearer token, verified)
    2. ``request.session['workspace_id']`` (reserved for future cookie flows)
    3. ``X-Workspace-ID`` header — **only** in non-prod and for anonymous requests
       (prod + authenticated + no JWT claim → rejected before domain fallback)
       (prod authenticated requests must use JWT to prevent header spoofing)
    4. Hostname (optionally from ``X-Forwarded-Host``) via WorkspaceDomain
    5. PUBLIC_PATHS / WORKSPACE_DELEGATING_HEADERS → let through, workspace=None
    6. Otherwise: 400 workspace_required

    After workspace binding, authenticated users with no membership → 403.

    A try/finally clears the thread-local in every code path so a
    Gunicorn/uvicorn worker reusing the same OS thread across requests
    can never inherit another tenant's workspace.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_workspace(None)
        try:
            return self._dispatch(request)
        finally:
            set_current_workspace(None)

    def _dispatch(self, request):
        path = request.path

        if self._is_public(path):
            request.workspace = None
            return self.get_response(request)

        workspace = self._resolve_workspace(request)

        if workspace is None:
            if self._delegates_to_view_auth(request):
                request.workspace = None
                return self.get_response(request)
            logger.warning(
                "tenant_isolation: rejecting request %s %s — no workspace resolvable",
                request.method, request.path,
            )
            return JsonResponse(MISSING_WORKSPACE_RESPONSE, status=400)

        request.workspace = workspace
        set_current_workspace(workspace)
        _hydrate_workspace_access(request, workspace)

        # Defense-in-depth: authenticated user with no membership → 403.
        user = getattr(request, 'user', None)
        if (
            user and getattr(user, 'is_authenticated', False)
            and not getattr(user, 'is_superuser', False)
            and not request.is_staff_member
            and not request.is_customer
        ):
            logger.warning(
                "tenant_isolation: authenticated user %s has no membership in workspace %s",
                user.id, workspace.id,
            )
            return JsonResponse(WORKSPACE_ACCESS_DENIED_RESPONSE, status=403)

        return self.get_response(request)

    # ─── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _is_public(path):
        return any(path.startswith(prefix) for prefix in PUBLIC_PATHS)

    @staticmethod
    def _delegates_to_view_auth(request):
        return any(header in request.headers for header in WORKSPACE_DELEGATING_HEADERS)

    @staticmethod
    def _resolve_workspace(request):
        # 1. JWT claim (authenticated requests in prod — prevents header spoofing)
        jwt_ws_id, jwt_valid = _decode_jwt_workspace_id(request)
        if jwt_ws_id is not None:
            return _get_workspace_by_id(jwt_ws_id)

        # 2. Session (reserved for cookie-based flows)
        session_ws_id = request.session.get('workspace_id') if hasattr(request, 'session') else None
        if session_ws_id is not None:
            return _get_workspace_by_id(session_ws_id)

        # 3. X-Workspace-ID header — only trusted in non-prod or for anonymous users.
        #    In prod, authenticated callers must use JWT (claim already checked above).
        #    A request with an *invalid/expired* Bearer token is treated as anonymous:
        #    DRF auth will reject the token at the view layer, so letting the request
        #    fall through to domain resolution is safe and avoids breaking public
        #    endpoints (e.g. storefront) when the client's access token has expired.
        is_prod = getattr(settings, 'IS_PROD', False)
        if is_prod and jwt_valid:
            # JWT valid but carried no workspace_id claim — reject before domain
            # fallback to prevent accidental cross-tenant resolution via hostname.
            return None
        ws_id = request.headers.get('X-Workspace-ID')
        if ws_id:
            return _get_workspace_by_id(ws_id)

        # 4. Domain-based lookup (storefront / anonymous)
        forwarded_host = request.META.get('HTTP_X_FORWARDED_HOST')
        host = (forwarded_host or request.get_host()).split(':')[0]
        hostname = host.strip()
        if hostname:
            return _get_workspace_by_domain(hostname)
        return None


class AuditLogMiddleware:
    """Capture request metadata for audit logging (unchanged by PR-04)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.audit_ip = self._client_ip(request)
        request.audit_user_agent = request.META.get('HTTP_USER_AGENT', '')
        return self.get_response(request)

    @staticmethod
    def _client_ip(request):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')

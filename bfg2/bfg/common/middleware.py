# -*- coding: utf-8 -*-
"""
Middleware for BFG2 multi-tenancy support.
"""

import logging
import threading
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.http import Http404
from django.core.cache import cache
from .models import Workspace, WorkspaceDomain, get_workspace_domain_cache_key, normalize_hostname

logger = logging.getLogger(__name__)

# Thread-local storage for current workspace
_thread_locals = threading.local()

# Cache timeout for workspace lookups (10 minutes)
WORKSPACE_CACHE_TIMEOUT = 600


def get_current_workspace():
    """Get the current workspace from thread-local storage."""
    return getattr(_thread_locals, 'workspace', None)


def set_current_workspace(workspace):
    """Set the current workspace in thread-local storage."""
    _thread_locals.workspace = workspace


def _get_workspace_by_domain(hostname):
    """Get workspace by exact WorkspaceDomain hostname match with caching."""
    normalized = normalize_hostname(hostname)
    if not normalized:
        return None

    cache_key = get_workspace_domain_cache_key(normalized)
    workspace = cache.get(cache_key)
    if workspace is not None:
        return workspace

    try:
        domain = (
            WorkspaceDomain.objects.filter(hostname=normalized, workspace__is_active=True)
            .select_related('workspace')
            .first()
        )
        workspace = domain.workspace if domain and domain.workspace_id else None
        cache.set(cache_key, workspace, WORKSPACE_CACHE_TIMEOUT)
        return workspace
    except Exception as e:
        logger.error(f"Error getting workspace for domain {normalized}: {e}")
        cache.set(cache_key, None, WORKSPACE_CACHE_TIMEOUT)
        return None


def _get_workspace_by_id(workspace_id):
    """
    Get workspace by ID with caching.
    
    Args:
        workspace_id: Workspace ID
        
    Returns:
        Workspace or None
    """
    try:
        workspace_id = int(workspace_id)
    except (ValueError, TypeError):
        return None
    
    cache_key = f'workspace:id:{workspace_id}'
    
    # Try cache first
    workspace = cache.get(cache_key)
    if workspace is not None:
        # Verify workspace is still active
        if workspace and workspace.is_active:
            return workspace
        # If cached workspace is inactive, invalidate cache and return None
        cache.delete(cache_key)
        return None
    
    # Query database
    try:
        workspace = Workspace.objects.get(id=workspace_id, is_active=True)
        # Cache the result
        cache.set(cache_key, workspace, WORKSPACE_CACHE_TIMEOUT)
        return workspace
    except Workspace.DoesNotExist:
        # Cache None result
        cache.set(cache_key, None, WORKSPACE_CACHE_TIMEOUT)
        return None


def _get_first_active_workspace():
    """
    Get first active workspace with caching.
    
    Returns:
        Workspace or None
    """
    cache_key = 'workspace:first_active'
    
    # Try cache first
    workspace = cache.get(cache_key)
    if workspace is not None:
        # Verify workspace is still active
        if workspace and workspace.is_active:
            return workspace
        # If cached workspace is inactive, invalidate cache
        cache.delete(cache_key)
    
    # Query database
    workspace = Workspace.objects.filter(is_active=True).first()
    
    # Cache the result (even if None)
    cache.set(cache_key, workspace, WORKSPACE_CACHE_TIMEOUT)
    return workspace


def invalidate_workspace_cache(workspace):
    """
    Invalidate all cache entries for a workspace.
    Should be called when workspace or its domain routing changes.
    """
    if not workspace:
        return

    for hostname in workspace.domains.values_list('hostname', flat=True):
        if hostname:
            cache.delete(get_workspace_domain_cache_key(hostname))

    cache.delete(f'workspace:id:{workspace.id}')
    cache.delete(f'workspace:frontend-base-url:{workspace.id}')
    cache.delete('workspace:first_active')


def _hydrate_workspace_access(request, workspace):
    """Populate request.is_staff_member / request.is_customer for the current workspace."""
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

    from bfg.common.models import StaffMember, Customer

    cache_key = f"user_ws_access:{user.id}:{workspace.id}"
    access_status = cache.get(cache_key)

    if access_status is None:
        is_staff = StaffMember.objects.filter(
            workspace=workspace,
            user=user,
            is_active=True,
        ).exists()
        is_customer = Customer.objects.filter(
            workspace=workspace,
            user=user,
            is_active=True,
        ).exists()
        access_status = {
            'is_staff_member': is_staff,
            'is_customer': is_customer,
        }
        cache.set(cache_key, access_status, WORKSPACE_CACHE_TIMEOUT)

    request.is_staff_member = bool(access_status.get('is_staff_member', False))
    request.is_customer = bool(access_status.get('is_customer', False))


class WorkspaceMiddleware(MiddlewareMixin):
    """
    Middleware to identify and set the current workspace based on the request domain.
    Uses caching to reduce database queries.
    """

    # Paths that operate outside any workspace context (Platform APIs, internal auth,
    # auth endpoints). Do NOT fallback to a random workspace for these — they either
    # work without a workspace or the caller must provide X-Workspace-ID explicitly.
    WORKSPACE_EXEMPT_PREFIXES = (
        '/api/v1/platform/',
        '/api/v1/internal/',
        '/api/v1/auth/',
    )

    def process_request(self, request):
        """Identify workspace: X-Workspace-ID header first (for API), then domain, then first active."""
        workspace = None

        # 1. Prefer X-Workspace-ID header so API clients (e.g. Next.js with NEXT_PUBLIC_WORKSPACE_ID) can override domain
        workspace_id = request.headers.get('X-Workspace-ID')
        if workspace_id:
            workspace = _get_workspace_by_id(workspace_id)

        if not workspace:
            # 2. Try workspace by domain (with cache). Use X-Forwarded-Host when set (e.g. from Next.js auth/storefront so domain matches the site the user is visiting).
            forwarded_host = request.META.get('HTTP_X_FORWARDED_HOST')
            host = (forwarded_host or request.get_host()).split(':')[0]
            hostname = host.strip()
            workspace = _get_workspace_by_domain(hostname)

        if not workspace:
            # 3. Fall back to the first active workspace — but NOT for paths that
            #    are designed to work without workspace context (platform, auth, internal).
            path = request.path
            is_exempt = any(path.startswith(prefix) for prefix in self.WORKSPACE_EXEMPT_PREFIXES)
            if not is_exempt:
                workspace = _get_first_active_workspace()

        # Set workspace in request and thread-local
        request.workspace = workspace
        if workspace:
            set_current_workspace(workspace)
        else:
            # Clear thread-local if no workspace
            if hasattr(_thread_locals, 'workspace'):
                delattr(_thread_locals, 'workspace')

        # Populate workspace-scoped role flags for downstream views.
        _hydrate_workspace_access(request, workspace)
        
        return None
    
    def process_response(self, request, response):
        """Clean up thread-local storage."""
        # Clear the workspace from thread-local after request
        if hasattr(_thread_locals, 'workspace'):
            del _thread_locals.workspace
        return response


class AuditLogMiddleware(MiddlewareMixin):
    """
    Middleware to capture request information for audit logging.
    """
    
    def process_request(self, request):
        """Store request info for audit logging."""
        request.audit_ip = self.get_client_ip(request)
        request.audit_user_agent = request.META.get('HTTP_USER_AGENT', '')
        return None
    
    @staticmethod
    def get_client_ip(request):
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

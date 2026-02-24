# -*- coding: utf-8 -*-
"""
Middleware for BFG2 multi-tenancy support.
"""

import threading
from django.utils.deprecation import MiddlewareMixin
from django.http import Http404
from django.core.cache import cache
from .models import Workspace

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
    """
    Get workspace by domain with caching.
    
    Args:
        hostname: Domain hostname
        
    Returns:
        Workspace or None
    """
    cache_key = f'workspace:domain:{hostname}'
    
    # Try cache first
    workspace = cache.get(cache_key)
    if workspace is not None:
        return workspace
    
    # Query database
    try:
        # Use filter().first() instead of get() to handle multiple workspaces gracefully
        workspace = Workspace.objects.filter(domain=hostname, is_active=True).order_by('id').first()
        if workspace:
            # Cache the result
            cache.set(cache_key, workspace, WORKSPACE_CACHE_TIMEOUT)
            return workspace
        else:
            # Cache None result to avoid repeated DB queries for non-existent domains
            cache.set(cache_key, None, WORKSPACE_CACHE_TIMEOUT)
            return None
    except Exception as e:
        # Log error but don't crash
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting workspace for domain {hostname}: {e}")
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
    Should be called when workspace is updated (domain, is_active, etc.).
    
    Args:
        workspace: Workspace instance
    """
    if not workspace:
        return
    
    # Invalidate domain cache
    if workspace.domain:
        cache.delete(f'workspace:domain:{workspace.domain}')
    
    # Invalidate ID cache
    cache.delete(f'workspace:id:{workspace.id}')
    
    # Invalidate first_active cache (since it might have changed)
    cache.delete('workspace:first_active')


class WorkspaceMiddleware(MiddlewareMixin):
    """
    Middleware to identify and set the current workspace based on the request domain.
    Uses caching to reduce database queries.
    """
    
    def process_request(self, request):
        """Identify workspace: X-Workspace-ID header first (for API), then domain, then first active."""
        workspace = None

        # 1. Prefer X-Workspace-ID header so API clients (e.g. Next.js with NEXT_PUBLIC_WORKSPACE_ID) can override domain
        workspace_id = request.headers.get('X-Workspace-ID')
        if workspace_id:
            workspace = _get_workspace_by_id(workspace_id)

        if not workspace:
            # 2. Try workspace by domain (with cache)
            hostname = request.get_host().split(':')[0]
            workspace = _get_workspace_by_domain(hostname)

        if not workspace:
            # 3. Fall back to the first active workspace
            workspace = _get_first_active_workspace()

        # Set workspace in request and thread-local
        request.workspace = workspace
        if workspace:
            set_current_workspace(workspace)
        else:
            # Clear thread-local if no workspace
            if hasattr(_thread_locals, 'workspace'):
                delattr(_thread_locals, 'workspace')
        
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

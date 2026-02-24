# -*- coding: utf-8 -*-


def create_staff_roles(workspace, roles):
    """
    Utility function to create staff roles for a workspace.
    Can be called by any module during workspace initialization.
    
    Args:
        workspace: Workspace instance
        roles: List of role data dictionaries containing:
            - code: Role code (required)
            - name: Role name (required)
            - description: Role description (optional)
            - permissions: Permission dict (optional)
            - is_system: Whether it's a system role (default: False)
            
    Returns:
        Number of roles created
        
    Example:
        from bfg.common.utils import create_staff_roles
        
        roles = [
            {
                'code': 'admin',
                'name': 'Administrator',
                'description': 'Full access',
                'permissions': {'*': ['create', 'read', 'update', 'delete']},
                'is_system': True,
            }
        ]
        create_staff_roles(workspace, roles)
    """
    from bfg.common.models import StaffRole
    import logging
    
    logger = logging.getLogger(__name__)
    created_count = 0
    
    for role_data in roles:
        try:
            _, created = StaffRole.objects.get_or_create(
                workspace=workspace,
                code=role_data['code'],
                defaults={
                    'name': role_data['name'],
                    'description': role_data.get('description', ''),
                    'permissions': role_data.get('permissions', {}),
                    'is_system': role_data.get('is_system', False),
                }
            )
            if created:
                created_count += 1
        except Exception as e:
            logger.error(f"Failed to create role {role_data.get('code')}: {e}")
    
    return created_count
"""
Utility functions for BFG Common module.
"""

import threading
from django.utils.crypto import get_random_string
from rest_framework.exceptions import PermissionDenied


_thread_locals = threading.local()


def get_current_workspace():
    """
    Get the current workspace from thread-local storage.
    Set by WorkspaceMiddleware.
    """
    return getattr(_thread_locals, 'workspace', None)


def set_current_workspace(workspace):
    """Set the current workspace in thread-local storage."""
    _thread_locals.workspace = workspace


def generate_unique_code(prefix='', length=8):
    """
    Generate a unique random code.
    
    Args:
        prefix: Prefix for the code
        length: Length of the random part
        
    Returns:
        Unique code string
    """
    random_part = get_random_string(length=length, allowed_chars='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    return f"{prefix}{random_part}" if prefix else random_part


def format_currency(amount, currency='NZD'):
    """
    Format amount as currency string.
    
    Args:
        amount: Decimal amount
        currency: Currency code
        
    Returns:
        Formatted currency string
    """
    currency_symbols = {
        'NZD': 'NZ$',
        'USD': 'US$',
        'CNY': '¥',
        'EUR': '€',
        'GBP': '£',
    }
    
    symbol = currency_symbols.get(currency, currency)
    return f"{symbol}{amount:,.2f}"


def get_client_ip(request):
    """
    Extract client IP address from request.
    
    Args:
        request: HttpRequest object
        
    Returns:
        IP address string
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    return ip


def get_required_workspace(request, allow_fallback_in_debug=True):
    """
    Get workspace from request, raising PermissionDenied if not found.
    
    This function ensures workspace is always available for multi-tenant operations.
    It should be used in ViewSets that require workspace context to prevent
    cross-workspace data access issues.
    
    Args:
        request: HttpRequest object with workspace attribute (set by WorkspaceMiddleware)
        allow_fallback_in_debug: If True, in DEBUG mode fallback to first active workspace
                                 (should be False in production to prevent data leaks)
    
    Returns:
        Workspace: Workspace instance
        
    Raises:
        PermissionDenied: If workspace is not found and cannot be determined
    """
    workspace = getattr(request, 'workspace', None)
    
    if workspace:
        return workspace
    
    # Only allow fallback in DEBUG mode to prevent production data leaks
    if allow_fallback_in_debug:
        from django.conf import settings
        if getattr(settings, 'DEBUG', False):
            from .models import Workspace
            workspace = Workspace.objects.filter(is_active=True).first()
            if workspace:
                # Log warning in DEBUG mode about fallback behavior
                import warnings
                warnings.warn(
                    f"Workspace not found in request, using first active workspace "
                    f"(ID: {workspace.id}). This should not happen in production. "
                    f"Ensure X-Workspace-ID header is provided.",
                    UserWarning
                )
                return workspace
    
    raise PermissionDenied(
        "Workspace is required. Please provide X-Workspace-ID header or ensure "
        "a workspace is set via domain mapping."
    )


def get_smtp_config_from_env():
    """
    Build SMTP config dict for EmailConfig from env (EMAIL_HOST, EMAIL_PORT, etc.).
    Single place for env var names; used by create_default_email_config command and tests.
    """
    import os
    port = 1025
    try:
        port = int(os.environ.get('EMAIL_PORT', '1025'))
    except ValueError:
        pass
    return {
        'host': os.environ.get('EMAIL_HOST', 'localhost'),
        'port': port,
        'use_tls': os.environ.get('EMAIL_USE_TLS', 'false').lower() == 'true',
        'use_ssl': os.environ.get('EMAIL_USE_SSL', 'false').lower() == 'true',
        'user': os.environ.get('EMAIL_HOST_USER', ''),
        'password': os.environ.get('EMAIL_HOST_PASSWORD', ''),
        'from_email': os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@example.com'),
    }

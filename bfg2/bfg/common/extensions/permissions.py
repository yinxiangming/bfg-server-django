# -*- coding: utf-8 -*-
"""
Refuse requests to an extension the workspace has not switched on.

    from bfg.common.extensions.permissions import RequiresExtension

    class ListingViewSet(viewsets.ModelViewSet):
        permission_classes = [IsWorkspaceStaff, RequiresExtension]

The extension is the one whose manifest the view's app ships; a view can name another
with ``required_extension = '<key>'``. The check runs with the view's other permission
classes, after authentication, so it sees a workspace bound while authenticating an
API key as well as the one the middleware resolved. List it after the classes that
decide who the caller is, so an anonymous caller is still asked to sign in first.
"""

from __future__ import annotations

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from bfg.common.extensions import registry, services

EXTENSION_DISABLED = 'extension_disabled'


def extension_key_for_view(view) -> str:
    """The key ``RequiresExtension`` checks for ``view``."""
    key = getattr(view, 'required_extension', None)
    if key:
        return key
    app_config = apps.get_containing_app_config(type(view).__module__)
    manifest = registry.manifest_for_app(app_config.label) if app_config is not None else None
    if manifest is None:
        raise ImproperlyConfigured(
            f'{type(view).__name__} uses RequiresExtension, but its app ships no extension manifest. '
            f'Set required_extension on the view.'
        )
    return manifest.key


class RequiresExtension(permissions.BasePermission):
    """Let the request through only while the view's extension is available to the workspace."""

    def has_permission(self, request, view):
        key = extension_key_for_view(view)
        if services.is_available(getattr(request, 'workspace', None), key):
            return True
        # Raised instead of returning False: DRF answers a denied anonymous request with
        # "not authenticated", which would send a caller the view lets in anonymously off
        # to sign in when the extension is simply switched off.
        raise PermissionDenied({
            'code': EXTENSION_DISABLED,
            'detail': f'{key} is not enabled for this workspace.',
        })

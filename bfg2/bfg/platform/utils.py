# -*- coding: utf-8 -*-
"""
Platform mode utilities.

Detects whether the platform extension is running in embedded mode
(same process/DB as workspaces) or standalone mode (dedicated instance).
"""
from django.conf import settings
from django.apps import apps


def is_embedded_mode() -> bool:
    """Return True when running in embedded mode (single BFG instance)."""
    return getattr(settings, "PLATFORM_EMBEDDED", False)


def get_platform_workspace():
    """Return the management Workspace instance (embedded mode only)."""
    slug = getattr(settings, "PLATFORM_WORKSPACE_SLUG", "")
    if not slug:
        return None
    Workspace = apps.get_model("common", "Workspace")
    try:
        return Workspace.objects.get(slug=slug)
    except Workspace.DoesNotExist:
        return None


def is_platform_workspace(workspace) -> bool:
    """Check whether *workspace* is the management Workspace."""
    slug = getattr(settings, "PLATFORM_WORKSPACE_SLUG", "")
    return bool(slug) and workspace.slug == slug

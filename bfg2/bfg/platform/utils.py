# -*- coding: utf-8 -*-
"""
Platform mode utilities.

Detects whether the platform extension is running in embedded mode
(same process/DB as workspaces) or standalone mode (dedicated instance).
"""
from contextlib import contextmanager

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


@contextmanager
def bound_workspace(workspace):
    """Bind *workspace* to the thread for the block, then put back what was there.

    Platform paths are public, so no workspace is bound to these requests. What
    runs for a particular workspace while one is being served — an extension hook,
    a service in another app — may still read tenant-scoped models through
    ``objects``, which answers nothing at all when no workspace is bound. Binding
    it for the duration is what lets those calls work; restoring the previous
    binding is what keeps the rest of the request seeing what it did before,
    since some services bind a workspace and never unbind it.
    """
    from bfg.common.middleware import get_current_workspace, set_current_workspace

    previous = get_current_workspace()
    set_current_workspace(workspace)
    try:
        yield
    finally:
        set_current_workspace(previous)

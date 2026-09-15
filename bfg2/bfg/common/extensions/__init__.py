# -*- coding: utf-8 -*-
"""
Extensions a workspace can switch on or off.

An extension author imports the manifest types from here. Everything that needs to
know whether an extension is live for a workspace asks ``is_available``; scheduled
work asks ``workspaces_with``, lists filter with ``where_available``, and event
listeners register with ``listen_for``. Views refuse requests with
``permissions.RequiresExtension``. Code that collects what every installed app
contributes leaves out the apps in ``unavailable_apps``. The platform console shows
and changes a workspace's extensions through ``endpoints``. See ``manifest``,
``registry``, ``services``, ``events``, ``permissions`` and ``endpoints``.
"""

from bfg.common.extensions.manifest import (  # noqa: F401
    PRICING_ADDON,
    PRICING_CORE,
    PUBLIC_SURFACES,
    SCOPE_PLATFORM,
    SCOPE_TOOLING,
    SCOPE_WORKSPACE,
    SURFACE_ACCOUNT,
    SURFACE_ADMIN,
    SURFACE_MINIPROGRAM,
    SURFACE_STOREFRONT,
    ExtensionManifest,
    Prerequisite,
    setting_present,
)


def is_available(workspace, key):
    """Whether the extension ``key`` is live for ``workspace`` right now."""
    from bfg.common.extensions import services

    return services.is_available(workspace, key)


def available_keys(workspace):
    """Keys of every extension live for ``workspace``, cached per workspace."""
    from bfg.common.extensions import services

    return services.available_keys(workspace)


def workspaces_with(key):
    """Active workspaces for which the extension ``key`` is available."""
    from bfg.common.extensions import services

    return services.workspaces_with(key)


def where_available(key, *, workspace_field='workspace'):
    """A ``Q`` keeping the rows whose workspace has ``key`` active; see ``services.where_available``."""
    from bfg.common.extensions import services

    return services.where_available(key, workspace_field=workspace_field)


def unavailable_apps(workspace):
    """Labels of the apps whose extension is not available to ``workspace``; see ``services.unavailable_apps``."""
    from bfg.common.extensions import services

    return services.unavailable_apps(workspace)


def listen_for(key, event_name, callback, *, workspace_of=None):
    """Register an event listener that hears only the workspaces using ``key``; see ``events.listen_for``."""
    from bfg.common.extensions import events

    return events.listen_for(key, event_name, callback, workspace_of=workspace_of)

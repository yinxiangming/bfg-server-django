# -*- coding: utf-8 -*-
"""
Extensions a workspace can switch on or off.

An extension author imports the manifest types from here. Everything that needs to
know whether an extension is live for a workspace asks ``is_available``; scheduled
work asks ``workspaces_with``. See ``manifest``, ``registry`` and ``services``.
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

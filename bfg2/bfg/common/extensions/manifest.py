# -*- coding: utf-8 -*-
"""
What an extension declares about itself.

An installed app that a workspace can switch on or off ships ``<app>/extension.py``
with a module-level ``EXTENSION = ExtensionManifest(...)``. The manifest is code, not
data: it is deployed with the app, so "deployed" simply means the app is installed
and its manifest was found (see ``registry``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from django.conf import settings

# Switched on per workspace; everything the extension contributes is gated on it.
SCOPE_WORKSPACE = 'workspace'
# Infrastructure every workspace relies on; always available, never activated.
SCOPE_PLATFORM = 'platform'
# Management commands only; nothing to activate and nothing to gate.
SCOPE_TOOLING = 'tooling'
SCOPES = (SCOPE_WORKSPACE, SCOPE_PLATFORM, SCOPE_TOOLING)

# Included in the base plan.
PRICING_CORE = 'core'
# Obtained separately, even when its price is zero.
PRICING_ADDON = 'addon'
PRICINGS = (PRICING_CORE, PRICING_ADDON)

# Where an extension shows up. Public surfaces are announced in the storefront config,
# so a client knows which extension pages and slots to render; the admin surface is
# only ever reported to signed-in staff.
SURFACE_ADMIN = 'admin'
SURFACE_STOREFRONT = 'storefront'
SURFACE_ACCOUNT = 'account'
SURFACE_MINIPROGRAM = 'miniprogram'
PUBLIC_SURFACES = frozenset({SURFACE_STOREFRONT, SURFACE_ACCOUNT, SURFACE_MINIPROGRAM})

_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def is_extension_key(value) -> bool:
    """Whether ``value`` is shaped like an extension key.

    Public because a key turns up outside a manifest — written into an identifier
    and read back out of one — and whatever reads it there has to be able to tell
    a key from something that merely looks like one.
    """
    return bool(_KEY_PATTERN.match(value or ''))


@dataclass(frozen=True)
class Prerequisite:
    """A condition the deployment or workspace must meet before activation.

    ``check`` receives the workspace and returns truthy when the condition holds;
    ``message`` tells an administrator what is missing.
    """

    code: str
    message: str
    check: Callable[[Any], bool]

    def is_met(self, workspace) -> bool:
        return bool(self.check(workspace))


def setting_present(name: str) -> Prerequisite:
    """Require a non-empty Django setting, or an environment variable of that name."""
    return Prerequisite(
        code=f'setting:{name}',
        message=f'{name} is not configured on this deployment.',
        check=lambda workspace: bool(getattr(settings, name, None) or os.environ.get(name)),
    )


@dataclass(frozen=True)
class ExtensionManifest:
    """Everything BFG needs to know to offer, activate and gate one extension.

    ``name`` and ``description`` are what an administrator is shown; ``name_zh`` and
    ``description_zh`` are the Chinese versions, empty when there are none. ``icon`` names
    the icon shown with the extension, written as the setup checklist writes its icons
    (``tabler-puzzle``). ``admin_url`` is the path of the extension's page or settings in
    the admin, such as ``/admin/reviews``; a client resolves it against its own origin, so
    it must start with ``/`` and name no host.

    ``pricing`` defaults to add-on for workspace extensions and to core for the rest.
    ``requires`` names other extensions that must be available first; only workspace
    extensions can require anything, since the rest are always available. ``data_models``
    lists the ``app_label.ModelName`` tables the extension owns, which is what gets
    archived when a workspace stops using it; each of them must carry a ``workspace``
    relation, since that is what says whose rows they are. ``restore_converters`` maps an
    app label to ``(archive_manifest, model_label, rows) -> rows``, called when an archive
    written before that app's migrations moved is loaded back, and raising ``ValueError``
    to refuse: an app whose migrations have moved and that has no converter is not
    restored at all. ``clean_config`` validates and
    normalises a workspace's configuration, raising ``ValueError`` (or Django's
    ``ValidationError``) on bad input. ``on_activate`` and ``on_deactivate`` are called
    with ``(workspace, record)`` inside the transaction that changes the state, so a
    hook that raises leaves the state unchanged.
    """

    key: str
    name: str
    description: str = ''
    name_zh: str = ''
    description_zh: str = ''
    icon: str = ''
    admin_url: str = ''
    scope: str = SCOPE_WORKSPACE
    pricing: str = ''
    surfaces: Tuple[str, ...] = ()
    requires: Tuple[str, ...] = ()
    prerequisites: Tuple[Prerequisite, ...] = ()
    meters: Tuple[str, ...] = ()
    data_models: Tuple[str, ...] = ()
    restore_converters: Optional[dict] = None
    config_schema: Optional[dict] = None
    clean_config: Optional[Callable[[dict], dict]] = None
    on_activate: Optional[Callable[[Any, Any], None]] = None
    on_deactivate: Optional[Callable[[Any, Any], None]] = None
    # Filled in by the registry with the label of the app that shipped the manifest.
    app_label: str = ''

    def __post_init__(self):
        if not is_extension_key(self.key):
            raise ValueError(
                f'Extension key {self.key!r} must be lowercase letters, digits and underscores, '
                f'starting with a letter.'
            )
        if self.scope not in SCOPES:
            raise ValueError(f'Extension {self.key!r} has unknown scope {self.scope!r}.')
        if not self.pricing:
            # Frozen dataclass: the default depends on scope, so it is filled in here.
            object.__setattr__(self, 'pricing', PRICING_ADDON if self.scope == SCOPE_WORKSPACE else PRICING_CORE)
        if self.pricing not in PRICINGS:
            raise ValueError(f'Extension {self.key!r} has unknown pricing {self.pricing!r}.')
        if self.key in self.requires:
            raise ValueError(f'Extension {self.key!r} cannot require itself.')
        if self.requires and self.scope != SCOPE_WORKSPACE:
            raise ValueError(
                f'Extension {self.key!r} is always available, so it cannot require other extensions.'
            )
        # "//host/path" starts with "/" too, but takes the browser to another host, and so
        # does "/\host/path": browsers read a backslash in a URL as a slash.
        if self.admin_url and (not self.admin_url.startswith('/') or self.admin_url.startswith(('//', '/\\'))):
            raise ValueError(
                f'Extension {self.key!r} has admin_url {self.admin_url!r}, '
                f'which must be a path starting with "/" that names no host.'
            )

    @property
    def is_activatable(self) -> bool:
        return self.scope == SCOPE_WORKSPACE

    @property
    def has_public_surface(self) -> bool:
        return bool(PUBLIC_SURFACES.intersection(self.surfaces))

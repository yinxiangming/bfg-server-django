# -*- coding: utf-8 -*-
"""
Per-workspace configuration for address lookup.

The feature is off for every workspace until an operator turns it on, because it
spends money on someone else's API per keystroke. The switch and the market it is
restricted to live on the workspace
(``Settings.custom_settings['plugins']['address_lookup']``), so one deployment can
serve a New Zealand shop and a Chinese one without a redeploy. The workspace also
needs the geo extension switched on; while it is off that block is kept but ignored.

The API key is deliberately *not* part of that blob. It is a billed server
credential, and ``custom_settings`` is returned whole to anyone who can read the
admin settings endpoint — storing it there would hand the key to every staff user
with settings access. It comes from ``GOOGLE_MAPS_API_KEY`` in the server
environment instead, and is never echoed back to a client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from django.conf import settings as django_settings

from bfg.common.extensions import is_available

EXTENSION_KEY = 'geo'
SETTINGS_PATH = ('plugins', 'address_lookup')

# ISO 3166-1 alpha-2. Two letters, nothing else: the code is interpolated into a
# request to Google and used to filter what comes back, so a free-form string here
# would be both a bad filter and an injection surface.
COUNTRY_CODE_RE = re.compile(r'^[A-Za-z]{2}$')


@dataclass(frozen=True)
class AddressLookupConfig:
    """What the workspace has asked for, resolved against server config."""

    enabled: bool
    country_code: str
    language: str
    api_key: str
    # False while the workspace has the geo extension switched off.
    extension_on: bool = True

    @property
    def usable(self) -> bool:
        """On, restricted to a market, and with a key to spend against.

        A workspace that switched the feature on before anyone set
        ``GOOGLE_MAPS_API_KEY`` is *configured* but not *usable*; the endpoints
        report that difference rather than failing as if the operator had left the
        switch off. A workspace with the geo extension switched off is not usable
        either, whatever its settings say.
        """
        return self.extension_on and self.enabled and bool(self.country_code) and bool(self.api_key)


def _custom_settings(workspace) -> Dict[str, Any]:
    ws_settings = getattr(workspace, 'workspace_settings', None)
    custom = getattr(ws_settings, 'custom_settings', None)
    return custom if isinstance(custom, dict) else {}


def _node(workspace) -> Dict[str, Any]:
    node: Any = _custom_settings(workspace)
    for key in SETTINGS_PATH:
        if not isinstance(node, dict):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, dict) else {}


def normalise_country_code(value: Optional[str]) -> str:
    """Upper-case alpha-2, or empty for anything that is not one."""
    code = (value or '').strip()
    return code.upper() if COUNTRY_CODE_RE.match(code) else ''


def get_address_lookup_config(workspace) -> AddressLookupConfig:
    """
    Resolve the workspace's address-lookup settings.

    ``country_code`` falls back to the workspace's own market
    (``Settings.country``) when the plugin block does not name one, because that
    field already answers "which country is this shop for" and making an operator
    say it twice invites the two to disagree.

    ``language`` falls back to the workspace's default language: the whole point of
    a display name is that the shopper can read it.
    """
    node = _node(workspace)
    ws_settings = getattr(workspace, 'workspace_settings', None)

    country = normalise_country_code(node.get('country_code'))
    if not country:
        country = normalise_country_code(getattr(ws_settings, 'country', ''))

    language = (node.get('language') or '').strip()
    if not language:
        language = (getattr(ws_settings, 'default_language', '') or 'en').strip()

    return AddressLookupConfig(
        enabled=node.get('enabled') is True,
        country_code=country,
        language=language,
        api_key=(getattr(django_settings, 'GOOGLE_MAPS_API_KEY', '') or '').strip(),
        extension_on=is_available(workspace, EXTENSION_KEY),
    )

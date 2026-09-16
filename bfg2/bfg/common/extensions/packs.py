# -*- coding: utf-8 -*-
"""
Plan packs: the set of extensions a kind of shop starts with.

A deployment that ships more than a handful of extensions ends up answering the
same question for every new workspace — which of these does a shop like this one
need? A pack is that answer written down once: a name, the industries it suits,
and the extension keys it switches on.

Packs belong to the deployment, not to the library and not to any one extension
(a pack spans several, and which extensions exist is a deployment's business),
so they are configured with ``BFG_EXTENSION_PLAN_PACKS`` — a mapping, or the
dotted path of one::

    BFG_EXTENSION_PLAN_PACKS = {
        'boutique': {
            'name': 'Boutique',
            'name_zh': '精品店',
            'description': 'A small shop selling its own stock.',
            'industries': ('fashion', 'beauty'),
            'extensions': ('a_key', 'another_key'),
        },
    }

Unset, there are no packs and nothing here does anything.

**Applying a pack only ever switches things on.** It activates the keys the
workspace does not have yet and leaves everything else alone — including
extensions the pack does not mention, which a workspace may well have switched on
deliberately. Nothing here deactivates anything.

A key the workspace is not entitled to stops the pack at that key and no further:
it is reported with the reason and the rest of the pack still applies, so a pack
can be offered to somebody who has not bought everything in it. A deployment that
wants some of those obtained rather than skipped — an add-on that costs nothing is
the usual case, since nobody is being sold anything — names a callable in
``BFG_EXTENSION_PACK_OBTAIN``: ``(workspace, manifest) -> bool``, returning whether
the workspace may now have it. It is asked once per refused key, and only for keys
a pack named. Unset, nothing is obtained and every unentitled key is skipped.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils.module_loading import import_string

from bfg.common.extensions import registry
from bfg.common.extensions.services import ExtensionError, activate

# The code an activation refuses with when the workspace may not have the key at
# all, as opposed to the key being unusable for some other reason.
NOT_ENTITLED = 'not_entitled'

logger = logging.getLogger(__name__)

# What applying one key did, in the order a reader cares about.
OUTCOME_ACTIVATED = 'activated'
OUTCOME_ALREADY_ON = 'already_on'
OUTCOME_SKIPPED = 'skipped'


def _configured() -> Dict[str, Any]:
    packs = getattr(settings, 'BFG_EXTENSION_PLAN_PACKS', None) or {}
    if isinstance(packs, str):
        try:
            packs = import_string(packs)
        except ImportError:
            logger.exception('BFG_EXTENSION_PLAN_PACKS names %r, which cannot be imported', packs)
            return {}
    if callable(packs):
        packs = packs()
    if not isinstance(packs, dict):
        logger.warning('BFG_EXTENSION_PLAN_PACKS is %s, not a mapping; ignoring it', type(packs).__name__)
        return {}
    return packs


def _as_pack(key: str, definition: Dict[str, Any]) -> Dict[str, Any]:
    """One pack, with every field present and the keys it names known to exist.

    A pack naming an extension this deployment does not ship is a configuration
    mistake worth seeing rather than a crash later, so the unknown key is dropped
    here and logged once, where it can be read next to the pack that named it.
    """
    extensions, unknown = [], []
    for extension_key in definition.get('extensions') or ():
        (extensions if registry.get_manifest(extension_key) else unknown).append(extension_key)
    if unknown:
        logger.warning('Plan pack %r names extensions this deployment does not ship: %s', key, ', '.join(unknown))
    return {
        'key': key,
        'name': definition.get('name') or key,
        'name_zh': definition.get('name_zh') or '',
        'description': definition.get('description') or '',
        'description_zh': definition.get('description_zh') or '',
        'industries': tuple(definition.get('industries') or ()),
        'extensions': tuple(extensions),
    }


def all_packs() -> List[Dict[str, Any]]:
    """Every pack the deployment has configured, in the order it configured them."""
    return [_as_pack(key, definition or {}) for key, definition in _configured().items()]


def get_pack(key: str) -> Optional[Dict[str, Any]]:
    definition = _configured().get(key)
    return _as_pack(key, definition or {}) if definition is not None else None


def pack_for_industry(industry: str) -> Optional[Dict[str, Any]]:
    """The pack that claims ``industry``, or nothing.

    Two packs claiming one industry is a configuration mistake; the first wins,
    so the answer at least stays the same from one call to the next.
    """
    if not industry:
        return None
    for pack in all_packs():
        if industry in pack['industries']:
            return pack
    return None


def apply_pack(workspace, key: str, *, user=None) -> List[Dict[str, str]]:
    """Switch on what ``key`` names and ``workspace`` does not have yet.

    Returns one row per extension in the pack: what was tried and what came of
    it. A key that cannot be switched on — not entitled, a prerequisite the
    deployment has not met, something already archived — is reported with the
    reason the activation gave and does not stop the rest of the pack, because
    half a pack applied is worth more than none and the reasons differ per key.
    """
    pack = get_pack(key)
    if pack is None:
        raise ExtensionError('unknown_pack', f'No plan pack named {key!r} is configured.')

    from bfg.common.models import WorkspaceExtension

    # Read what the workspace has before changing any of it: ``activate`` returns
    # the same record whether it switched something on or found it on already, and
    # a pack applied to a shop that has most of it is the ordinary case worth
    # reporting accurately. ``all_objects`` because a pack is also applied from a
    # management command, where no workspace is bound to the thread.
    on_already = set(
        WorkspaceExtension.all_objects.filter(
            workspace=workspace,
            key__in=pack['extensions'],
            status=WorkspaceExtension.STATUS_ACTIVE,
        ).values_list('key', flat=True)
    )

    applied: List[Dict[str, str]] = []
    for extension_key in pack['extensions']:
        if extension_key in on_already:
            applied.append({'key': extension_key, 'outcome': OUTCOME_ALREADY_ON})
            continue
        try:
            activate(workspace, extension_key, user=user)
        except ExtensionError as error:
            if error.code == NOT_ENTITLED and _obtain(workspace, extension_key):
                # Obtaining one switches it on where the deployment does that, so
                # ask again rather than assume either way.
                try:
                    activate(workspace, extension_key, user=user)
                except ExtensionError as second:
                    error = second
                else:
                    applied.append({'key': extension_key, 'outcome': OUTCOME_ACTIVATED})
                    continue
            applied.append({
                'key': extension_key,
                'outcome': OUTCOME_SKIPPED,
                'code': error.code,
                'detail': error.message,
            })
            continue
        applied.append({'key': extension_key, 'outcome': OUTCOME_ACTIVATED})
    return applied


def _obtain(workspace, key: str) -> bool:
    """Ask the deployment whether ``workspace`` may now have ``key``, free of charge.

    Whatever the deployment names here is doing something that costs somebody
    something — writing an entitlement, at least — so a failure in it is worth
    seeing, and is not worth failing a pack over: it means the key is skipped, the
    same as if the deployment had said no.
    """
    path = getattr(settings, 'BFG_EXTENSION_PACK_OBTAIN', '')
    if not path:
        return False
    try:
        return bool(import_string(path)(workspace, registry.get_manifest(key)))
    except Exception:
        logger.exception('Could not obtain %s for workspace %s while applying a pack', key, workspace)
        return False

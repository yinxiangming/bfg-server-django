# -*- coding: utf-8 -*-
"""Discovery, validation and application of deployed storefront skins."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from bfg.common.extensions import registry
from bfg.common.storefront_cache import invalidate_storefront_config_cache

CORE_STOREFRONT_SKINS = frozenset({'store', 'website'})


def available_storefront_skins(extension_keys: Iterable[str] | None = None) -> frozenset[str]:
    """Return core skins plus skins declared by the selected deployed extensions.

    ``None`` selects every deployed manifest. Passing extension keys restricts the
    answer to those manifests, which lets provisioning validate against exactly the
    extensions it will activate.
    """
    if extension_keys is None:
        selected = None
    elif isinstance(extension_keys, str):
        selected = {extension_keys}
    else:
        selected = set(extension_keys)
    skins = set(CORE_STOREFRONT_SKINS)
    for manifest in registry.all_manifests():
        if selected is None or manifest.key in selected:
            skins.update(manifest.storefront_skins)
    return frozenset(skins)


def validate_storefront_skin(value, extension_keys: Iterable[str] | None = None) -> str:
    """Normalise a skin name, returning blank unchanged and rejecting unavailable skins."""
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('Storefront skin must be a string.')
    skin = value.strip()
    if not skin:
        return ''
    if skin not in available_storefront_skins(extension_keys):
        raise ValueError(f'Unknown or unavailable storefront skin {skin!r}.')
    return skin


@transaction.atomic
def set_storefront_skin(
    workspace,
    skin,
    *,
    extension_keys: Iterable[str] | None = None,
    only_if_empty: bool = False,
) -> bool:
    """Write a validated skin to a workspace, optionally preserving any configured theme."""
    from bfg.common.models import Settings

    skin = validate_storefront_skin(skin, extension_keys)
    if not skin:
        return False
    settings_obj, _ = Settings.objects.select_for_update().get_or_create(workspace=workspace)
    custom = dict(settings_obj.custom_settings or {})
    storefront_ui = dict(custom.get('storefront_ui') or {})
    current = storefront_ui.get('theme')
    if only_if_empty:
        is_empty = current is None or (isinstance(current, str) and not current.strip())
        if not is_empty:
            return False
    if current == skin:
        return False
    storefront_ui['theme'] = skin
    custom['storefront_ui'] = storefront_ui
    settings_obj.custom_settings = custom
    settings_obj.save(update_fields=['custom_settings', 'updated_at'])
    transaction.on_commit(lambda: invalidate_storefront_config_cache(workspace.id))
    return True

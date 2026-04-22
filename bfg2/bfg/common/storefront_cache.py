# -*- coding: utf-8 -*-
"""Storefront public config cache (``GET /api/v1/settings/storefront/``)."""

from __future__ import annotations

# Languages used when invalidating cached payloads (must cover storefront query params).
STOREFRONT_CONFIG_LANGS: tuple[str, ...] = ('en', 'zh-hans', 'zh-hant')


def storefront_config_cache_key(workspace_id: int, lang: str) -> str:
    return f'storefront_config:{workspace_id}:{lang}'


def invalidate_storefront_config_cache(workspace_id: int | None) -> None:
    """Delete cached storefront JSON for all supported ``lang`` values."""
    if workspace_id is None:
        return
    from django.core.cache import cache

    for lang in STOREFRONT_CONFIG_LANGS:
        cache.delete(storefront_config_cache_key(workspace_id, lang))

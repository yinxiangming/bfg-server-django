# -*- coding: utf-8 -*-
"""Refresh window for workspace-scoped cache entries.

Workspace lookups, resolved frontend base URLs and the public storefront config are all
derived from admin-editable rows, so they share one refresh window: the TTL is the longest
an admin's change can take to reach a visitor when no explicit invalidation fires.

Deployments that point ``DJANGO_CACHE_URL`` at Redis share one cache across every worker
and can afford a longer window. Without it Django falls back to a per-process LocMemCache,
where nothing invalidates a sibling worker's copy and the TTL is the only bound on how long
two workers can disagree — so the default stays short.
"""

from __future__ import annotations

from django.conf import settings

# 5 minutes. Override per deployment with ``BFG_CACHE_TTL`` (seconds).
DEFAULT_CACHE_TTL = 300


def cache_ttl() -> int:
    """Seconds to keep workspace-scoped cache entries."""
    try:
        return int(getattr(settings, 'BFG_CACHE_TTL', DEFAULT_CACHE_TTL))
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL

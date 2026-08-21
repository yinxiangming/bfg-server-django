# -*- coding: utf-8 -*-
"""Contract for the shared workspace-cache TTL (``bfg.common.cache_policy``).

The TTL bounds how long a stale storefront payload or workspace lookup can survive
an admin edit, so the default is pinned here rather than left to whatever the call
sites happen to pass.
"""

import pytest

from bfg.common.cache_policy import DEFAULT_CACHE_TTL, cache_ttl


def test_default_is_five_minutes():
    assert DEFAULT_CACHE_TTL == 300


def test_uses_default_when_setting_absent(settings):
    del settings.BFG_CACHE_TTL
    assert cache_ttl() == DEFAULT_CACHE_TTL


def test_setting_overrides_default(settings):
    settings.BFG_CACHE_TTL = 900
    assert cache_ttl() == 900


@pytest.mark.parametrize("bad", ["", "abc", None, [30]])
def test_unparseable_setting_falls_back_rather_than_raising(settings, bad):
    # A typo in DJANGO env config must not take every cached read down with it.
    settings.BFG_CACHE_TTL = bad
    assert cache_ttl() == DEFAULT_CACHE_TTL


def test_numeric_string_is_accepted(settings):
    # Env vars arrive as strings even when settings.py forgets to coerce.
    settings.BFG_CACHE_TTL = "60"
    assert cache_ttl() == 60

# -*- coding: utf-8 -*-
"""
Whether a workspace has fallen far enough behind to be made read only.

A base plan that is not renewed runs on for ``grace_days`` after its period ends
(``entitlements.live_filter``). Once even that has run out the workspace keeps
everything it has — nothing is deleted, nothing is hidden — but may no longer be
written to: the shop can be browsed and the back office read, and the writes that
are still allowed are the ones marked with
``bfg.core.read_only.exempt_from_read_only``.

**This is off unless a deployment switches it on, and it must stay that way.**
The question "does this workspace have a base plan" is answered from the
``platform.WorkspaceEntitlement`` table, and a deployment that has never sold
anything has no rows in it — so every workspace it runs would answer "no" and be
locked the moment the code arrived. Hence ``BFG_READ_ONLY_WHEN_UNENTITLED``,
default ``False``, checked before anything else happens: with the switch off this
module does no work and asks the database nothing at all.

The same trap applies to a deployment that does sell: **write the entitlement
rows for every existing workspace before switching this on**, or they will all be
read only together. See ``docs/reference/server-switches.md``.

Everything here reads ``all_objects`` through ``entitlements``, because the
question is also asked where no workspace is bound to the thread.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# The switch. Named on the settings module, not in the database: a deployment
# that has to unlock every workspace at once — because the entitlement rows turned
# out to be wrong — should be able to do it by restarting with the switch off,
# without the database it may not trust answering first.
SETTING = "BFG_READ_ONLY_WHEN_UNENTITLED"

# How long an answer is reused, in seconds. The same minute ``billing`` reuses its
# overdue answer for, and for the same reason: this is asked on every write a
# workspace makes, and a query per write to learn something that changes once a
# month is not worth it. The minute cuts both ways — a workspace that has just
# lapsed keeps writing for up to a minute, and one that has just paid stays locked
# for up to a minute. The first is harmless; the second is why paying should call
# ``forget`` (see below) rather than wait.
CACHE_SECONDS = 60


def _cache_key(workspace_id: int) -> str:
    return f"platform:read-only:{workspace_id}"


def _workspace_id(workspace):
    """The id of ``workspace``, which may be a model instance or an id already."""
    if workspace is None:
        return None
    if isinstance(workspace, int):
        return workspace
    return getattr(workspace, "pk", None)


def enabled() -> bool:
    """Whether this deployment has switched read-only mode on at all.

    Checked first by every caller, so that a deployment that has not switched it
    on pays one ``getattr`` and nothing else — no query, no cache round trip.
    """
    return bool(getattr(settings, SETTING, False))


def is_read_only(workspace) -> bool:
    """Whether ``workspace`` may only be read right now.

    ``workspace`` is a ``common.Workspace`` or its id. ``False`` for no workspace
    at all: a request that belongs to no tenant is not one this can speak for.

    **Fails open, deliberately.** If the question cannot be answered — the
    database is unreachable, a row is malformed, anything at all — this returns
    ``False`` and logs it at ERROR. Letting one write through that should have
    been refused costs the deployment a little money it is already owed; refusing
    every write closes a shop that is trading, and it would be closed by the very
    failure that stops anyone diagnosing it. Nothing is cached in that case, so
    the next request asks again rather than inheriting a minute of the mistake.
    """
    if not enabled():
        return False

    workspace_id = _workspace_id(workspace)
    if workspace_id is None:
        return False

    cache_key = _cache_key(workspace_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    try:
        # Imported here rather than at module scope: this module is imported by
        # the middleware on every request, and the models it would pull in need
        # the app registry to be ready.
        from bfg.platform.services.entitlements import is_entitled

        # Passed on as given: the filter inside takes a workspace or its id
        # equally, so an id caller does not have to fetch a row to ask.
        entitled = is_entitled(workspace)
    except Exception:
        logger.exception(
            "Could not tell whether workspace %s still has a base plan; "
            "treating it as writable",
            workspace_id,
        )
        return False

    cache.set(cache_key, 0 if entitled else 1, CACHE_SECONDS)
    return not entitled


def forget(workspace) -> None:
    """Drop the cached answer for ``workspace``, so the next ask is a fresh one.

    For whatever settles a payment: writing a new entitlement period unlocks the
    workspace, and a shop that has just paid should not spend the rest of the
    cache window unable to trade. Safe to call when nothing was cached, and safe
    to call when the switch is off.
    """
    workspace_id = _workspace_id(workspace)
    if workspace_id is None:
        return
    cache.delete(_cache_key(workspace_id))

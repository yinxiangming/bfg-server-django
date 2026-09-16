# -*- coding: utf-8 -*-
"""
Whether a workspace may use an add-on, and how it came to.

``entitlement_check`` is what a deployment that sells extensions points
``BFG_EXTENSION_ENTITLEMENT_CHECK`` at. It is **not** wired up by default, and no
settings module in this library names it: a deployment that does not sell anything
has no entitlement rows, so switching this on there would make every add-on
unavailable at once. See ``docs/reference/server-switches.md``.

Like ``usage``, everything here reads ``all_objects`` and filters by workspace
itself, because entitlement questions are asked from scheduled work and from the
platform console, where no workspace is bound to the thread.
"""

from __future__ import annotations

import calendar
from datetime import timedelta
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from bfg.common.extensions.manifest import PRICING_CORE, ExtensionManifest
from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.services.platform_variables import get_variable


def _add_months(moment, months: int):
    """``moment`` moved on by whole calendar months, clamped to the month's length.

    A period that starts on the 31st ends on the 30th of a month that has thirty
    days, rather than spilling into the next one.
    """
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1]))


def live_filter(at=None) -> Q:
    """The rule for an entitlement that grants use of its key at ``at`` (default now).

    The one place the rule is written. Everything that has to know whether an
    entitlement counts — one row, a workspace's rows, a report over all of them —
    filters with this, so none of them can drift from the others.

    An active entitlement counts while its period runs, and for the deployment's
    ``grace_days`` after it ends; one with no period end does not expire. An
    entitlement already moved to ``grace`` counts until ``grace_until`` passes, or
    indefinitely when no deadline has been set. ``ended`` never counts.

    Time arithmetic is done here rather than in SQL: ``now <= period end + grace``
    is the same question as ``period end >= now - grace``, and the second needs no
    date arithmetic from the database, so it is one indexable comparison on every
    backend.
    """
    now = at or timezone.now()
    cutoff = now - timedelta(days=get_variable("grace_days"))
    return (
        Q(status=WorkspaceEntitlement.STATUS_ACTIVE)
        & (Q(current_period_end__isnull=True) | Q(current_period_end__gte=cutoff))
    ) | (
        Q(status=WorkspaceEntitlement.STATUS_GRACE)
        & (Q(grace_until__isnull=True) | Q(grace_until__gte=now))
    )


def is_entitled(workspace, key: str = WorkspaceEntitlement.KEY_BASE_PLAN) -> bool:
    """Whether ``workspace`` may use ``key`` right now.

    ``key`` is an add-on's extension key, or the default for the base plan itself.
    A workspace may hold several rows for one key — renewals leave the old ones —
    and one live row is enough, which is one query however many it has.

    An entitlement lapses on time rather than on being swept: a period that ran
    out longer ago than the grace period stops counting whether or not anything
    has moved the row to ``ended``. The job that closes periods settles the status
    and does what a status change entails — pausing what the workspace was using,
    telling it why — but nothing keeps working merely because that job has not run.
    """
    if workspace is None:
        return False
    return (
        WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key)
        .filter(live_filter())
        .exists()
    )


def grant(
    workspace,
    key: str = WorkspaceEntitlement.KEY_BASE_PLAN,
    *,
    months: Optional[int] = None,
    plan=None,
    reason: str = "",
) -> WorkspaceEntitlement:
    """Give ``workspace`` an entitlement to ``key`` without it being bought.

    For a trial, a plan bundled with an agreement, or an apology. ``months`` is
    how long it runs; left empty the entitlement does not expire, which is what a
    permanently included add-on looks like. ``plan`` records which plan it stands
    for, when it stands for one.
    """
    now = timezone.now()
    period_end = _add_months(now, months) if months else None
    return WorkspaceEntitlement.all_objects.create(
        workspace=workspace,
        key=key,
        plan=plan,
        source=WorkspaceEntitlement.SOURCE_GRANTED,
        starts_at=now,
        current_period_end=period_end,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        reason=reason,
    )


def entitlement_check(workspace, manifest: ExtensionManifest) -> bool:
    """``BFG_EXTENSION_ENTITLEMENT_CHECK`` for a deployment that sells extensions.

    Called by ``bfg.common.extensions.services`` for every workspace-scoped
    extension a workspace has switched on, and again before it may switch one on.
    Extensions priced as part of the base plan are always allowed; the rest have to
    be entitled.
    """
    if manifest.pricing == PRICING_CORE:
        return True
    return is_entitled(workspace, manifest.key)

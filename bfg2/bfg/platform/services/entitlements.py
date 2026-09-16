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

from django.db import transaction
from django.db.models import DateTimeField, DurationField, ExpressionWrapper, F, Q, Value
from django.utils import timezone

from bfg.common.extensions.manifest import PRICING_CORE, ExtensionManifest
from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.services.platform_variables import get_variable

# Written to the rows the sweep settles, so that a workspace asking why something
# stopped is answered by the row itself rather than by a log nobody kept.
ENDED_REASON = "grace period ended without a renewal"
# ``WorkspaceExtension.status_reason`` holds 64 characters and is read by code as
# well as by people, so this one is a token rather than a sentence.
PAUSED_REASON = "entitlement_ended"


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


# ── Closing periods that have run out ────────────────────────────────


def _pause_extensions(pairs, at) -> int:
    """Pause the extension records of ``pairs``, and return how many were paused.

    ``pairs`` is ``(workspace id, key)`` for entitlements the sweep has just ended.
    Pausing keeps the workspace's data and configuration and only stops the
    extension being available, so paying again is all it takes to get it back.

    A pair the workspace still holds a live entitlement for is left alone: a
    renewal writes a new row rather than moving the old one, so one row ending is
    not the same as the workspace losing the key.
    """
    from bfg.common.extensions import services as extension_services
    from bfg.common.models import WorkspaceExtension

    # The base plan is not an extension; there is no record to pause for it.
    wanted = {pair for pair in pairs if pair[1] != WorkspaceEntitlement.KEY_BASE_PLAN}
    if not wanted:
        return 0

    workspace_ids = {workspace_id for workspace_id, _ in wanted}
    keys = {key for _, key in wanted}
    still_entitled = set(
        WorkspaceEntitlement.all_objects.filter(workspace_id__in=workspace_ids, key__in=keys)
        .filter(live_filter(at))
        .values_list("workspace_id", "key")
    )
    lapsed = wanted - still_entitled
    if not lapsed:
        return 0

    # Two ``__in`` filters match pairs neither of them names — workspace A's key and
    # workspace B's — so the rows are picked out in Python rather than with one OR
    # term per pair. That is two queries however large the sweep, and SQL whose size
    # does not grow with it.
    rows = (
        WorkspaceExtension.all_objects.filter(
            workspace_id__in={workspace_id for workspace_id, _ in lapsed},
            key__in={key for _, key in lapsed},
            status=WorkspaceExtension.STATUS_ACTIVE,
        )
        .values_list("id", "workspace_id", "key")
    )
    to_pause = [row_id for row_id, workspace_id, key in rows if (workspace_id, key) in lapsed]
    if not to_pause:
        return 0

    paused = WorkspaceExtension.all_objects.filter(id__in=to_pause).update(
        status=WorkspaceExtension.STATUS_PAUSED,
        status_reason=PAUSED_REASON,
        status_changed_at=at,
        # Nobody switched it off, so the field that names who did is emptied rather
        # than left pointing at whoever switched it on.
        status_changed_by=None,
        # ``auto_now`` does not fire for a queryset update.
        updated_at=timezone.now(),
    )
    affected = sorted(
        {workspace_id for _, workspace_id, key in rows if (workspace_id, key) in lapsed}
    )
    # After the commit: a reader that refilled the cache from rows as they still
    # were would otherwise keep serving the extension as available.
    transaction.on_commit(
        lambda: [extension_services.invalidate(workspace_id) for workspace_id in affected]
    )
    return paused


@transaction.atomic
def close_due_periods(at=None) -> dict:
    """Settle every entitlement whose period, or grace, has run out by ``at``.

    Two steps, in one pass. An ``active`` row whose ``current_period_end`` has
    passed moves to ``grace``, with a deadline of the deployment's ``grace_days``
    after the period ended. A ``grace`` row whose deadline has passed moves to
    ``ended``, and the extension it paid for is paused — its data and configuration
    kept — unless the workspace holds another live entitlement for the same key.
    A row whose period ended longer ago than the grace period goes through both
    steps in the same run, which is what makes one late sweep settle correctly
    rather than granting a fresh grace period.

    Called from the ``close_entitlement_periods`` management command, on whatever
    schedule the deployment can offer. Nothing keeps working merely because this
    has not run: ``live_filter`` already stops counting an active row past its
    period and grace, so the sweep settles the status and does what a status change
    entails rather than being what makes an entitlement lapse. Running it late
    therefore delays the pause, not the expiry.

    Idempotent: a second run finds nothing, because each step only matches the
    status the previous one moved the row out of. Everything is done in bulk, so
    the number of queries is the same for one workspace and for ten thousand.

    Returns how many rows each step settled. Raises nothing of its own; a database
    error rolls the whole sweep back, leaving every row as it was for the next run.
    """
    now = at or timezone.now()
    grace_days = get_variable("grace_days")

    moved_to_grace = WorkspaceEntitlement.all_objects.filter(
        status=WorkspaceEntitlement.STATUS_ACTIVE,
        current_period_end__isnull=False,
        current_period_end__lt=now,
    ).update(
        status=WorkspaceEntitlement.STATUS_GRACE,
        # The deadline is counted from the period's own end rather than from now,
        # so a sweep that runs late does not hand out grace it did not owe.
        grace_until=ExpressionWrapper(
            F("current_period_end") + Value(timedelta(days=grace_days), output_field=DurationField()),
            output_field=DateTimeField(),
        ),
        updated_at=timezone.now(),
    )

    lapsed = list(
        WorkspaceEntitlement.all_objects.filter(
            status=WorkspaceEntitlement.STATUS_GRACE,
            grace_until__isnull=False,
            grace_until__lt=now,
        ).values_list("id", "workspace_id", "key")
    )
    ended = 0
    paused = 0
    if lapsed:
        ended = WorkspaceEntitlement.all_objects.filter(
            id__in=[row_id for row_id, _, _ in lapsed],
            # Still the status it was read as. Nothing holds these rows between the
            # read and the write, so a second sweep running alongside this one — or
            # an operator ending a row for a refund in between — would otherwise
            # have its reason overwritten by this one's, and be counted twice.
            status=WorkspaceEntitlement.STATUS_GRACE,
        ).update(
            status=WorkspaceEntitlement.STATUS_ENDED,
            ended_reason=ENDED_REASON,
            updated_at=timezone.now(),
        )
        # After the rows are ended, so that a key whose only entitlement this was
        # no longer looks live to the check inside. Every pair read is offered,
        # including any the guard above declined to end because something else had
        # already ended it: whether the extension should still be running is a
        # question ``_pause_extensions`` answers for itself, and one sweep leaving
        # it to the other would leave it running for a day.
        paused = _pause_extensions(
            {(workspace_id, key) for _, workspace_id, key in lapsed}, now
        )

    return {"moved_to_grace": moved_to_grace, "ended": ended, "extensions_paused": paused}

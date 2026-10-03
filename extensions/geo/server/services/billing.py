# -*- coding: utf-8 -*-
"""
Turning Google's session pricing into what a workspace is charged.

Google prices an address lookup as a session rather than as requests. Every
autocomplete request made under one session token is free if that session ends in
a chosen address, because the place details call that follows is charged for the
session as a whole; a session the shopper abandons is charged per autocomplete
request instead.

That is the whole of the rule, and it is why nothing here meters an autocomplete
request as it happens: whether it costs anything is not known until the session
ends, one way or the other. Instead:

* :func:`note_autocomplete` counts the request against the open session;
* :func:`close_session` drops the session when an address was picked — the details
  call is metered by the caller and the counted requests are never billed;
* :func:`settle_abandoned` bills the sessions that went quiet and forgets them.

The alternative approaches were both rejected. Metering every keystroke and
crediting it back when a session completes bills a workspace for almost every
lookup it makes and then unbills most of it — the ledger stops meaning anything,
and a crash between the two halves overcharges. Counting in the cache alone loses
whatever is owed whenever the cache is flushed, restarted or evicted, which is
exactly when a busy workspace has the most sessions open.

Settlement runs off the back of live requests because neither environment runs
Celery beat, so there is no scheduled job to put it in. It only ever touches the
workspace making the request, and only a bounded number of its rows. The price of
that is worth stating plainly: a workspace that stops making address lookups
altogether — it switched the extension off, or the shop went quiet — leaves
whatever its last shoppers abandoned sitting there unsettled, because the request
that would have settled it never comes. That is a handful of rows and a few cents
per workspace, and they are settled the moment lookups resume. A deployment that
grows a scheduler should call :func:`settle_abandoned` from it and stop leaning on
live traffic for this.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.geo.extension import METER_AUTOCOMPLETE
from apps.geo.models import AutocompleteSession
from bfg.platform import metering

logger = logging.getLogger(__name__)

# How long a session may go untouched before the shopper is taken to have left.
# Comfortably longer than someone hesitating over a form or answering the door,
# and short enough that what is owed is settled the same afternoon it was run up.
SESSION_IDLE_TIMEOUT = timedelta(minutes=30)

# The most sessions one request will settle. Settlement is paid for by whoever
# happens to make the next request, so it has to cost about the same every time;
# a workspace that somehow built up a backlog works through it a batch per request
# rather than making one shopper wait for all of it.
SETTLE_BATCH = 50


def note_autocomplete(workspace, token: str) -> None:
    """Count one autocomplete request against ``workspace``'s session ``token``.

    Deliberately not metered: this request is free if the session ends in a chosen
    address. The count is what :func:`settle_abandoned` bills if it does not.

    The count is incremented in the database rather than read and written back,
    because a shopper types faster than a request takes to finish and two
    keystrokes in flight at once would otherwise each store the total they read.
    """
    if not token:
        return
    now = timezone.now()
    try:
        updated = AutocompleteSession.all_objects.filter(workspace=workspace, token=token).update(
            request_count=F('request_count') + 1,
            last_request_at=now,
        )
        if updated:
            return
        try:
            # Its own transaction: on a duplicate the INSERT fails, and without
            # this an enclosing transaction would be left unusable.
            with transaction.atomic():
                AutocompleteSession.all_objects.create(
                    workspace=workspace,
                    token=token,
                    request_count=1,
                    started_at=now,
                    last_request_at=now,
                )
        except IntegrityError:
            # Two keystrokes opened the same session at the same moment. The other
            # one created the row, so this request is an increment after all.
            AutocompleteSession.all_objects.filter(workspace=workspace, token=token).update(
                request_count=F('request_count') + 1,
                last_request_at=now,
            )
    except Exception:
        # The provider call has already been made and paid for. Losing the count
        # for one request undercharges by a fraction of a cent; failing the
        # request here would waste what was just spent and lose the shopper's
        # suggestions with it.
        logger.exception(
            'Could not count an autocomplete request for workspace %s',
            getattr(workspace, 'pk', None),
        )


def close_session(workspace, token: str) -> None:
    """Forget ``token``'s session, unbilled, because it ended in a chosen address.

    Called once the place details call has been metered. From Google's point of
    view that one call covers the whole session, so the autocomplete requests
    counted against it are free and the row has nothing left to say.
    """
    if not token:
        return
    try:
        AutocompleteSession.all_objects.filter(workspace=workspace, token=token).delete()
    except Exception:
        # Same reasoning as above, and the row is harmless if it survives: it goes
        # quiet from here, so settlement will pick it up. That overcharges the
        # workspace for suggestions it did use, which is the direction to err in
        # only because the alternative is failing a request that already succeeded.
        logger.exception(
            'Could not close autocomplete session for workspace %s',
            getattr(workspace, 'pk', None),
        )


def _stale_sessions(workspace, cutoff):
    """``workspace``'s sessions last touched before ``cutoff``, oldest first, capped."""
    return list(
        AutocompleteSession.all_objects
        .filter(workspace=workspace, last_request_at__lt=cutoff)
        .order_by('last_request_at')
        .values_list('pk', 'request_count')[:SETTLE_BATCH]
    )


def settle_abandoned(workspace, *, now=None) -> int:
    """Bill and forget ``workspace``'s sessions that were dropped rather than finished.

    A session nobody has touched for :data:`SESSION_IDLE_TIMEOUT` is one the
    shopper left; Google charges for each of its autocomplete requests, so this is
    where those requests are finally metered. Returns how many requests were
    billed, which is zero on the overwhelming majority of calls.

    Deleting a row is how this call claims it, and the claim is only allowed to
    land on a session that is *still* abandoned: the delete repeats the ``cutoff``
    that selected it. Between the two statements a shopper can come back to the
    form, and their keystroke moves ``last_request_at`` forward — the row then
    fails the delete, is not billed as abandoned, and goes on as the live session
    it is. Without that repeat it would be billed per request here and charged
    again as place details when the shopper picks their address, which is the same
    Google session paid for twice. Only the rows a call actually deleted are
    billed, so two sweeps running at once cannot bill one session between them
    either.

    Like the platform's ``meter``, this never raises: settling is bookkeeping, it
    runs ahead of work the caller has not done yet, and a lock wait that times out
    under one shopper must not take another shopper's lookup down with it. Under
    MySQL that is not a hypothetical — this is deletes and updates from every
    request landing on the same few rows. A failure is logged, whatever was
    deleted before it is still billed, and the rest waits for the next request.
    """
    cutoff = (now or timezone.now()) - SESSION_IDLE_TIMEOUT
    requests = 0
    try:
        for pk, count in _stale_sessions(workspace, cutoff):
            deleted, _ = AutocompleteSession.all_objects.filter(
                pk=pk, last_request_at__lt=cutoff
            ).delete()
            if deleted:
                requests += count
    except Exception:
        # Not re-raised, and not a reason to skip the meter below: the rows already
        # deleted are gone, and nothing else will ever account for them.
        logger.exception(
            'Could not settle abandoned autocomplete sessions for workspace %s',
            getattr(workspace, 'pk', None),
        )

    if requests:
        # One record for the batch rather than one per session: usage is rolled up
        # per meter and day anyway, and this is one write instead of fifty.
        metering.meter(workspace, METER_AUTOCOMPLETE, requests)
    return requests

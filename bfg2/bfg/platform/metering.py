# -*- coding: utf-8 -*-
"""
The two calls an extension makes around anything that costs money.

Ask first, then spend, then count::

    from bfg.platform import metering

    if not metering.allowed(workspace, 'vendor.lookup'):
        raise SomethingTheCallerCanShowTheUser()
    result = vendor.lookup(query)          # only now is money spent
    metering.meter(workspace, 'vendor.lookup')

In that order because the two calls answer different questions and fail
differently. ``allowed`` decides whether the workspace may spend, before anything
has been spent, and says so plainly — a caller that ignores it bills a workspace
past its cap. ``meter`` records what was spent, after the vendor call succeeded,
and never raises: a bill that is short by one call is a smaller problem than a
request that fails after the work was already done and paid for.

A meter belongs to the extension whose manifest declares it in ``meters``. One
that no manifest declares is part of the base platform: there is no extension to
switch off, so it is not gated on one, but it still counts against the cap.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from bfg.common.extensions import is_available, registry
from bfg.platform.models.metering import UsageRecord
from bfg.platform.services import pricing, usage

logger = logging.getLogger(__name__)

# How often one unpriced meter is worth mentioning. A meter is wired up before it
# is priced every time something new is rolled out, and until the price row exists
# every single call would otherwise write a line with a stack trace in it. An hour
# is often enough that the gap shows up in any hour's logs someone reads, and rare
# enough that it cannot drown anything out.
UNPRICED_LOG_INTERVAL_SECONDS = 3600
# Per process, not shared: this is on the path of every paid call, and coordinating
# through a cache to save log lines would be paying in the thing that matters to
# save the thing that does not. A deployment running four workers therefore says it
# four times an hour, which is still four lines rather than four thousand. Plain
# dictionary writes, which are atomic enough for a counter whose worst failure is
# one extra line.
_unpriced_logged_at: Dict[str, float] = {}


def extension_for_meter(meter_name: str) -> Optional[str]:
    """The key of the extension that declares ``meter_name``, if one does."""
    for manifest in registry.all_manifests():
        if meter_name in manifest.meters:
            return manifest.key
    return None


def allowed(workspace, meter_name: str) -> bool:
    """Whether ``workspace`` may make a call metered as ``meter_name`` right now.

    Asked before the call. It is true when the extension the meter belongs to is
    available to the workspace — deployed, switched on, entitled — and the
    workspace has not used up this month's points.

    It does not swallow failures: a caller must not be told a workspace may spend
    because the question could not be answered.
    """
    if workspace is None:
        return False
    key = extension_for_meter(meter_name)
    if key is not None and not is_available(workspace, key):
        return False
    return usage.may_meter(workspace)


def _note_unpriced(meter_name: str) -> None:
    """Say that ``meter_name`` has no price, at most once an hour per process.

    A warning rather than an error with a stack trace: nothing is broken in the
    code, a price row is missing, and the traceback would be the same one every
    time. What is worth knowing is which meter and that it is still happening,
    which is what the line says.
    """
    now = time.monotonic()
    last = _unpriced_logged_at.get(meter_name)
    if last is not None and now - last < UNPRICED_LOG_INTERVAL_SECONDS:
        return
    _unpriced_logged_at[meter_name] = now
    logger.warning(
        "Meter %s has no price, so nothing is being billed for it; "
        "price it with the meter_prices command. Reported at most every %s seconds.",
        meter_name, UNPRICED_LOG_INTERVAL_SECONDS,
    )


def meter(workspace, meter_name: str, quantity=1) -> Optional[UsageRecord]:
    """Record that ``workspace`` made a call metered as ``meter_name``.

    Called once the call has succeeded, so that what is billed is what was
    delivered. Returns the day's usage row, or ``None`` when the usage could not
    be recorded — an unpriced meter, or the database being unavailable. Those are
    logged and swallowed: the caller has already done its work, and failing its
    request now would not unspend the money.

    A meter nobody has priced yet is the one failure that is expected: metering is
    wired up before the price row exists every time something is rolled out. It is
    logged as a warning, once an hour per meter, so that a gap in pricing is
    visible without every call writing a stack trace. Everything else keeps its.
    """
    try:
        return usage.record_usage(workspace, meter_name, quantity)
    except pricing.MeterNotPriced:
        _note_unpriced(meter_name)
        return None
    except Exception:
        logger.exception(
            "Could not record %s of meter %s for workspace %s",
            quantity, meter_name, getattr(workspace, "pk", None),
        )
        return None

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
from typing import Optional

from bfg.common.extensions import is_available, registry
from bfg.platform.models.metering import UsageRecord
from bfg.platform.services import usage

logger = logging.getLogger(__name__)


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


def meter(workspace, meter_name: str, quantity=1) -> Optional[UsageRecord]:
    """Record that ``workspace`` made a call metered as ``meter_name``.

    Called once the call has succeeded, so that what is billed is what was
    delivered. Returns the day's usage row, or ``None`` when the usage could not
    be recorded — an unpriced meter, or the database being unavailable. Those are
    logged and swallowed: the caller has already done its work, and failing its
    request now would not unspend the money.
    """
    try:
        return usage.record_usage(workspace, meter_name, quantity)
    except Exception:
        logger.exception(
            "Could not record %s of meter %s for workspace %s",
            quantity, meter_name, getattr(workspace, "pk", None),
        )
        return None

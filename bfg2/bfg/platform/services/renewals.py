# -*- coding: utf-8 -*-
"""
Turning a paid platform bill into another period of everything it renewed.

Issuing a bill records purchases that have already happened; it deliberately
writes nothing forward, because a bill is not a payment. This is the other half:
once the bill has been paid, each entitlement it charged a renewal for is given
its next period, and the row that was running out is settled. Without it a
workspace that pays on time still loses its add-ons when the grace period ends.

Driven by the deployment's own events rather than by a schedule — see
``bfg.platform.handlers`` — so an entitlement comes back as soon as the money
does, whether that is a card through a gateway or a bank transfer somebody
reconciled. Only the management workspace's own invoices are acted on, and only
those whose number is one ``billing`` issued; every other invoice the deployment
settles is left alone.

Like the rest of the platform services, everything here reads ``all_objects`` and
filters by workspace itself: a payment is finalised with the *paying* workspace
bound to the thread, which is the management one, while the rows being renewed
belong to the workspace being billed.
"""

from __future__ import annotations

import logging
from typing import List

from django.db import transaction

from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.services import billing
from bfg.platform.services.entitlements import add_months
from bfg.platform.utils import get_platform_workspace

logger = logging.getLogger(__name__)

# How much of a period one bill buys. A bill covers a month of usage and the
# renewals that fell in it, so paying it buys the month after the one that ended.
RENEWAL_MONTHS = 1

# Written to the row a renewal replaces, so that a row in the history says why it
# stopped rather than looking like one that lapsed. ``ended_reason`` holds 255
# characters.
RENEWED_REASON = "renewed for the following period"

# The status an invoice has to be in for its renewals to be written. A payment
# that only covers part of a bill leaves the invoice unpaid, and nothing is
# renewed until the rest of it arrives.
PAID_STATUS = "paid"


def renew_for_invoice(invoice_id: int) -> List[WorkspaceEntitlement]:
    """Write the next period for everything one paid platform bill renewed.

    ``invoice_id`` is a ``finance.Invoice``. Anything that is not a paid platform
    bill is left alone and nothing is written: an invoice a workspace issued to
    its own customers, one belonging to another workspace, a number nothing of
    ours issued, or a bill a part payment has not settled.

    For each entitlement the bill charged a renewal for — the ones
    ``billing.renewal_period_bounds`` names, chosen the way ``issue_monthly_bills``
    priced them — a new row is written for the following month, carrying the same
    plan and marked as purchased. The row that ran out is left as history rather
    than moved on, so that what a workspace was entitled to last month can still
    be read; one already in ``grace`` is settled to ``ended``, since what it was
    waiting for has arrived. One still marked ``active`` is left to
    ``close_due_periods``, which will settle it and pause nothing, because the row
    written here is live by then.

    Idempotent, and safe against the same payment being reported twice at once:
    the invoice row is held for the duration, and a period is only written when no
    row for that key already ends at that moment. A second report therefore writes
    nothing rather than handing out a second month.

    A bill paid long after it was issued buys the month that followed the one it
    charged for, which may itself have passed — the workspace has paid for a month
    that ran, and the next bill buys the next one. It is not moved forward to
    whenever the money arrived, since that would make paying late cheaper than
    paying on time.

    An entitlement the bill charged for that can no longer be found is logged and
    skipped: a bill raised by hand has no renewal lines behind it, and neither does
    one whose entitlements were removed afterwards. Nothing here raises. It runs
    from a payment that has already been taken, and money that has changed hands
    must not be undone by a renewal that could not be written.

    Returns the rows written, in the order they were written.
    """
    from bfg.finance.models import Invoice

    platform_workspace = get_platform_workspace()
    if platform_workspace is None:
        return []

    # Read before locking: all but a handful of a deployment's payments are a
    # workspace's own, and those should cost a read rather than a write lock.
    number = (
        Invoice.all_objects.filter(pk=invoice_id, workspace=platform_workspace)
        .values_list("invoice_number", flat=True)
        .first()
    )
    if number is None:
        return []
    billed = billing.billed_workspace_and_period(number)
    if billed is None:
        # The management workspace's own invoice to one of its customers, or a
        # number entered by hand. Neither renews anything.
        return []

    workspace_id, period_start = billed
    with transaction.atomic():
        # The invoice is what two reports of the same payment have in common, and
        # it is one row that is always there, so it is what serialises them. The
        # status is re-read under the lock: a refund or a cancellation racing this
        # must not be overtaken by a renewal for a bill that is no longer paid.
        status = (
            Invoice.all_objects.select_for_update()
            .filter(pk=invoice_id)
            .values_list("status", flat=True)
            .first()
        )
        if status != PAID_STATUS:
            return []
        written = _write_next_periods(workspace_id, period_start, number)
        # After the commit, and after the periods above are part of it: metered
        # calls are refused on a cached answer, and a workspace that has just
        # settled up must not go on being told it owes money for the rest of that
        # minute. Dropped whether or not anything was renewed, since what made the
        # answer wrong was the bill being paid rather than the rows written.
        transaction.on_commit(lambda: billing.forget_overdue(workspace_id))
        return written


def _write_next_periods(workspace_id, period_start, invoice_number) -> List[WorkspaceEntitlement]:
    """The periods one paid bill buys, written inside the caller's transaction."""
    since, until = billing.renewal_period_bounds(period_start)
    charged = list(
        WorkspaceEntitlement.all_objects.filter(
            workspace_id=workspace_id,
            current_period_end__gte=since,
            current_period_end__lt=until,
            # Exactly what ``_renewal_lines`` charges for: an entitlement given
            # rather than bought costs nothing and so renews nothing, and one with
            # no plan had no price to put on the bill.
            source=WorkspaceEntitlement.SOURCE_PURCHASED,
            plan__isnull=False,
        ).order_by("key", "id")
    )
    if not charged:
        logger.info(
            "Invoice %s was paid, but workspace %s has no %s renewal to write a period for.",
            invoice_number, workspace_id, period_start.strftime("%Y-%m"),
        )
        return []

    written = []
    settled = []
    for row in charged:
        period_end = add_months(row.current_period_end, RENEWAL_MONTHS)
        if _already_renewed(workspace_id, row.key, period_end):
            continue
        written.append(
            WorkspaceEntitlement(
                workspace_id=workspace_id,
                key=row.key,
                plan_id=row.plan_id,
                source=WorkspaceEntitlement.SOURCE_PURCHASED,
                # The moment the last period ended, so that one entitlement's
                # periods meet rather than leaving a gap as long as the bill took
                # to pay.
                starts_at=row.current_period_end,
                current_period_end=period_end,
                status=WorkspaceEntitlement.STATUS_ACTIVE,
            )
        )
        if row.status == WorkspaceEntitlement.STATUS_GRACE:
            settled.append(row.pk)

    if not written:
        return []
    WorkspaceEntitlement.all_objects.bulk_create(written)
    if settled:
        WorkspaceEntitlement.all_objects.filter(
            id__in=settled,
            # Still the status it was read as, so that a sweep ending the same row
            # at the same moment does not have its reason overwritten by this one.
            status=WorkspaceEntitlement.STATUS_GRACE,
        ).update(status=WorkspaceEntitlement.STATUS_ENDED, ended_reason=RENEWED_REASON)
    logger.info(
        "Invoice %s renewed %s entitlement(s) for workspace %s.",
        invoice_number, len(written), workspace_id,
    )
    return written


def _already_renewed(workspace_id, key: str, period_end) -> bool:
    """Whether the period this renewal would write has been written already.

    What makes a payment reported twice harmless. The period a bill buys is worked
    out rather than counted, so a second report asks for a row that is already
    there and writes nothing — no flag to keep anywhere, and no window between
    asking and writing, because the invoice is held across both.
    """
    return WorkspaceEntitlement.all_objects.filter(
        workspace_id=workspace_id,
        key=key,
        source=WorkspaceEntitlement.SOURCE_PURCHASED,
        current_period_end=period_end,
    ).exists()

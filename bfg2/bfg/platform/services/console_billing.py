# -*- coding: utf-8 -*-
"""
What the console shows one workspace about what it has used and what it owes.

Two reports, both read-only and both about a single workspace: a month of metered
usage against the cap, and the platform bills issued for it. Everything is worked
out here rather than in the view, so that the shapes the console is written
against are one thing to read and one thing to test.

Money and points are Decimals all the way through and only turned into strings on
the way out. A point is a US dollar and a currency amount is not, so rendering
either as a JSON number would hand the console a float to do arithmetic on — see
``_amount``.

Platform endpoints bind no workspace to the request, so tenant-scoped models are
read through ``all_objects`` here, filtered by workspace by hand.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from bfg.common.constants import get_default_currency_for_workspace
from bfg.common.extensions import registry
from bfg.platform.metering import extension_for_meter
from bfg.platform.models.metering import UsageRecord
from bfg.platform.services import billing, exchange_rates, usage
from bfg.platform.utils import get_platform_workspace

ZERO = Decimal("0")
ONE = Decimal("1")

# Points and metered quantities are written to exactly as many places as the
# columns they were summed from hold. Read off the model rather than repeated
# here, and applied on the way out because a database that stores decimals as
# numbers hands back a sum with the trailing zeros dropped: without this the
# console would be given "22" on one backend and "22.00000000" on another for the
# same usage.
POINTS_PLACES = UsageRecord._meta.get_field("points").decimal_places
QUANTITY_PLACES = UsageRecord._meta.get_field("quantity").decimal_places

# How many bills the console is given. A workspace is billed monthly, so this is
# two years of them: enough to scroll through without the console having to page,
# and a bound on a list that would otherwise grow for as long as the workspace
# exists. Anything older is a question for whoever runs the deployment, which has
# the invoices themselves.
INVOICE_LIMIT = 24


def _amount(value: Optional[Decimal], places: Optional[int] = None) -> Optional[str]:
    """A Decimal as the string the console is given, or ``None`` left as it is.

    Every number in these reports is money or points, and JSON has no decimal: a
    float would round 0.1 to something that is not 0.1 and let the console add up
    a column into a total that is a cent out. A string is exact, and the console
    parses it with whatever it does its own arithmetic in.

    ``places`` writes the number to a fixed scale, for the figures that were summed
    rather than read from a column; without it the value is written as it stands.
    """
    if value is None:
        return None
    value = Decimal(value)
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places))
    return format(value, "f")


def _points(value: Decimal) -> str:
    return _amount(value, POINTS_PLACES)


def _quantity(value: Decimal) -> str:
    return _amount(value, QUANTITY_PLACES)


def _extensions_for(meter_names) -> dict:
    """``{meter: (extension key, the name it goes by)}`` for the meters in a report.

    A meter belongs to the extension whose manifest declares it, and one no
    manifest declares is part of the base platform — both halves of the key are
    then ``None``, which is the console's cue to show the meter on its own.

    Worked out once for the whole report rather than per row: the answer is the
    same on every day a meter was used, and ``extension_for_meter`` walks the
    deployed manifests to find it, so asking once a day would be that walk again
    for every line of the breakdown.
    """
    found = {}
    for name in set(meter_names):
        key = extension_for_meter(name)
        manifest = registry.get_manifest(key) if key is not None else None
        found[name] = (key, manifest.name if manifest is not None else None)
    return found


def _decimal_places(currency_code: str) -> int:
    """How many places an amount in ``currency_code`` is written to.

    The currency's own, capped the way ``billing`` caps it, so an estimate is
    written exactly as the bill for it will be. Two places for a currency this
    deployment has never used, which is what most of them have.
    """
    from bfg.finance.models import Currency

    places = (
        Currency.objects.filter(code=currency_code, is_active=True)
        .values_list("decimal_places", flat=True)
        .first()
    )
    if places is None:
        places = billing.ASSUMED_DECIMAL_PLACES
    return min(places, billing.INVOICE_DECIMAL_PLACES)


def usage_report(workspace, month=None) -> dict:
    """``workspace``'s metered usage for one month, against what it may spend.

    ``month`` is any date inside the month wanted, the current UTC month by
    default. ``meters`` totals the month by meter, heaviest first, and ``days``
    breaks it down by day, earliest first, with each day's own meters heaviest
    first — which is what a chart with a bar per day and a table beside it wants,
    from one query.

    Every meter entry carries the extension that declares it: ``extension`` is its
    key and ``extension_name`` the name on its manifest, both ``None`` for a meter
    that belongs to the base platform rather than to any extension. A meter name is
    an identifier the deployment chose and not something to show a shop owner, so
    the console has a name to put beside it without a second request.

    Points are US dollars and are reported as points; ``estimated_amount`` and
    each meter's ``amount`` are what they would come to in the workspace's own
    currency at today's rate. They are an estimate and say so: the bill is issued
    at the rate of the day it is issued on, not today's, and the month may not
    have finished. Where no rate has been stored for the pair, every converted
    figure is ``None`` rather than a number worked out at a rate nobody published.

    ``overdue`` is whether a platform bill is past due and unpaid, which is one of
    the two things that stop a workspace metering; the cap is the other.
    """
    first, _ = usage.month_bounds(month)
    currency_code = (get_default_currency_for_workspace(workspace) or billing.POINT_CURRENCY).upper()
    places = _decimal_places(currency_code)
    rate = _rate_to(currency_code)

    def converted(points: Decimal) -> Optional[str]:
        if rate is None:
            return None
        return _amount(billing.round_to(points * rate, places))

    rows = usage.usage_by_day(workspace, month=month)
    extensions = _extensions_for(row["meter"] for row in rows)

    def named(meter: str) -> dict:
        """What a meter is called, for a console that should not have to show a key."""
        key, name = extensions[meter]
        return {"meter": meter, "extension": key, "extension_name": name}

    # Totalled here rather than in a second aggregate query: the same rows answer
    # both breakdowns, and totals worked out from what is shown cannot disagree
    # with it.
    by_meter = defaultdict(lambda: {"quantity": ZERO, "points": ZERO})
    by_day = defaultdict(list)
    for row in rows:
        total = by_meter[row["meter"]]
        total["quantity"] += row["quantity"]
        total["points"] += row["points"]
        by_day[row["day"]].append(row)

    used = sum((row["points"] for row in rows), ZERO)
    # To the resolution a point is billed at, so that the cap reads the same
    # whether it came from the workspace's own column or the deployment's default.
    cap = Decimal(usage.monthly_cap(workspace)).quantize(billing.POINT_PRECISION)
    return {
        "month": f"{first:%Y-%m}",
        "currency": currency_code,
        "cap_points": _amount(cap),
        "used_points": _points(used),
        "remaining_points": _points(max(cap - used, ZERO)),
        "estimated_amount": converted(used),
        "overdue": billing.has_overdue_invoice(workspace),
        "meters": [
            {
                **named(meter),
                "quantity": _quantity(total["quantity"]),
                "points": _points(total["points"]),
                "amount": converted(total["points"]),
            }
            for meter, total in _heaviest_first(by_meter.items())
        ],
        "days": [
            {
                "day": day.isoformat(),
                "points": _points(sum((row["points"] for row in day_rows), ZERO)),
                "meters": [
                    {
                        **named(row["meter"]),
                        "quantity": _quantity(row["quantity"]),
                        "points": _points(row["points"]),
                    }
                    for row in sorted(day_rows, key=lambda row: (-row["points"], row["meter"]))
                ],
            }
            for day, day_rows in sorted(by_day.items())
        ],
    }


def _heaviest_first(items):
    """Meter totals ordered by points spent, then by name so ties do not shuffle."""
    return sorted(items, key=lambda item: (-item[1]["points"], item[0]))


def _rate_to(currency_code: str) -> Optional[Decimal]:
    """One point in ``currency_code`` at today's rate, or ``None`` if none is stored."""
    try:
        return exchange_rates.convert(ONE, billing.POINT_CURRENCY, currency_code)
    except exchange_rates.ExchangeRateNotFound:
        return None


def invoice_history(workspace, limit: int = INVOICE_LIMIT) -> list:
    """The platform bills issued for ``workspace``, newest first, at most ``limit``.

    ``limit`` defaults to ``INVOICE_LIMIT``, two years of monthly bills. A
    workspace old enough to have more is not given them all: this is the console's
    summary, and it is bounded rather than growing with the age of the account.
    There is no paging past it, so a caller that needs an older bill asks for it
    with a larger ``limit``.

    The bills belong to the management workspace and are found by the prefix of
    their number, which is the only thing tying one to the workspace it is about.
    Only that workspace's invoices are read, for the reason
    ``has_overdue_invoice`` gives: a workspace picks its own invoice prefix, so
    reading by number alone would show it another workspace's bills.

    ``status`` is ``finance.Invoice``'s own, and one of exactly five values — there
    is no ``void``:

    ``draft``      made out but not issued. ``issue_monthly_bills`` never leaves a
                   bill here, so one that is means somebody raised it by hand.
    ``sent``       issued, and its due date is running. What a bill is issued as.
    ``paid``       settled. A platform bill being paid is what renews the
                   entitlements it charged for; see ``services.renewals``.
    ``overdue``    issued, unpaid, and marked as late by hand. Nothing on the
                   platform billing path writes it — no bill is issued into it and
                   no sweep moves one there — so ``overdue`` the status and
                   ``overdue`` the field below are not the same thing, and a
                   console must not read either one off the other.
    ``cancelled``  written off. It is not a debt and never falls due.

    ``overdue`` is the field to colour a row by, and it is the rule
    ``has_overdue_invoice`` applies to all of a workspace's bills at once: unpaid
    (``draft``, ``sent`` or ``overdue`` — never ``paid`` or ``cancelled``), past
    its due date, and for more than nothing. The last of those is what keeps a
    month covered entirely by the trial credit from being shown as a debt: it is
    worth an invoice as a record of what was used, but there is nothing owed on it.
    A workspace whose usage report says ``overdue`` therefore always has at least
    one bill flagged here, and one whose report does not has none.

    An empty list when the deployment has no management workspace: nothing issues
    platform bills there, so there are none to show.
    """
    from bfg.finance.models import Invoice

    platform_workspace = get_platform_workspace()
    if platform_workspace is None or workspace is None or workspace.pk is None:
        return []

    today = timezone.now().date()
    invoices = (
        Invoice.all_objects.filter(
            workspace=platform_workspace,
            invoice_number__startswith=billing.invoice_number_prefix(workspace.pk),
        )
        .select_related("currency")
        .prefetch_related("items")
        # By id as well, so that bills issued on the same day come back in a fixed
        # order rather than whichever one the database reaches first.
        .order_by("-issue_date", "-id")[:limit]
    )
    return [_invoice_entry(invoice, today) for invoice in invoices]


def _invoice_entry(invoice, today: date) -> dict:
    billed = billing.billed_workspace_and_period(invoice.invoice_number)
    return {
        "id": invoice.pk,
        "number": invoice.invoice_number,
        "period": f"{billed[1]:%Y-%m}" if billed else "",
        "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "status": invoice.status,
        "paid_date": invoice.paid_date.isoformat() if invoice.paid_date else None,
        "overdue": bool(
            invoice.status in billing.UNPAID_STATUSES
            and invoice.due_date
            and invoice.due_date < today
            and invoice.total > ZERO
        ),
        "currency": invoice.currency.code if invoice.currency_id else "",
        "subtotal": _amount(invoice.subtotal),
        "tax": _amount(invoice.tax),
        "total": _amount(invoice.total),
        "items": [
            {
                "description": item.description,
                "quantity": _amount(item.quantity),
                "unit_price": _amount(item.unit_price),
                "subtotal": _amount(item.subtotal),
            }
            # In the order they were written, which is the order they were billed in.
            for item in sorted(invoice.items.all(), key=lambda item: item.pk)
        ],
    }

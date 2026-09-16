# -*- coding: utf-8 -*-
"""
Turning a month of usage and a set of renewals into invoices.

A bill is issued by the management workspace and made out to the owner of the
workspace being billed, because it is the deployment that is selling and the
owner who pays. It is written in the billed workspace's own currency, from points
that are US dollars, at the rate in force on the day it is issued.

An invoice is identified by a number the deployment builds itself — the prefix,
the billed workspace and the period — which is what keeps a month from being
billed twice. ``finance.Invoice`` is already unique on (workspace, number) within
the management workspace, so the database refuses the second attempt rather than
this module having to be the only thing that remembers. That number is also the
only link back from an invoice to the workspace it is about, since the invoice's
own workspace is the management one, and it is what ``has_overdue_invoice`` reads
— together with the management workspace itself, because a workspace can choose
what its own invoices are numbered.

Everything here reads ``all_objects`` and filters by workspace itself: billing
runs with no workspace bound to the thread, where the scoped manager is empty.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional, Tuple

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from bfg.common.constants import (
    get_default_country_for_workspace,
    get_default_currency_for_workspace,
)
from bfg.core.exceptions import BFGException
from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.models.metering import UsageRecord
from bfg.platform.models.workspace_profile import WorkspacePlatformProfile
from bfg.platform.services import exchange_rates, ownership, usage
from bfg.platform.services.platform_variables import get_variable
from bfg.platform.utils import get_platform_workspace, is_platform_workspace

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")

# A point is a US dollar, which is the currency every conversion starts from.
POINT_CURRENCY = "USD"
# ``InvoiceItem.quantity`` holds two decimal places, and a point is a dollar, so
# this is the same resolution the money itself is written at.
POINT_PRECISION = Decimal("0.01")
# What a currency's minor unit is when the deployment has no ``Currency`` row to
# read it from, which only happens on a dry run for a currency never used yet.
ASSUMED_DECIMAL_PLACES = 2
# As many places as ``Invoice`` and ``InvoiceItem`` hold. A currency row may claim
# more — nothing stops one being entered by hand — and a third decimal place would
# be quantised away on the way into the column, one line at a time, until the lines
# no longer added up to the invoice above them. Rounding to what the columns hold
# keeps that from happening quietly.
INVOICE_DECIMAL_PLACES = 2

# Every platform invoice number starts with this, so that one can be told from an
# invoice a workspace issued to its own customers.
INVOICE_PREFIX = "PLAT-"

# The one country whose tax is worked out. Everywhere else is billed untaxed for
# now — see ``_tax_percent``.
GST_COUNTRY = "NZ"

# An invoice in any of these has not been paid. ``paid`` and ``cancelled`` are
# what is left, and neither is something to stop a workspace over.
UNPAID_STATUSES = ("draft", "sent", "overdue")
# What an invoice is issued as: it has been made out and its due date is running,
# which is what ``sent`` means here. Nothing is emailed by this module.
ISSUED_STATUS = "sent"

# How long the answer to "does this workspace owe anything" is reused for. It is
# asked before every metered call, so it cannot be a query every time; and it
# decides whether a workspace can work, so a payment must take effect quickly. A
# minute is the same window the platform variables use, and it means a workspace
# that has just paid is unblocked before anyone thinks to complain.
OVERDUE_CACHE_SECONDS = 60


class PlatformWorkspaceMissing(BFGException):
    """The deployment has no management workspace to issue bills from"""

    default_message = "No platform workspace is configured"
    default_code = "platform_workspace_missing"


# ── Invoice numbers ──────────────────────────────────────────────────


def invoice_number_prefix(workspace_id: int) -> str:
    """What every platform invoice number for one workspace starts with.

    The trailing separator matters: without it workspace 1's prefix would also
    match workspace 12's invoices.
    """
    return f"{INVOICE_PREFIX}{workspace_id}-"


def invoice_number_for(workspace_id: int, period_start: date) -> str:
    """The number for one workspace's bill for one month.

    Worked out rather than counted up, so that issuing the same month twice is
    refused by the unique index on (workspace, invoice_number) instead of quietly
    producing a second invoice.
    """
    return f"{invoice_number_prefix(workspace_id)}{period_start:%Y%m}"


def billed_workspace_and_period(invoice_number: str) -> Optional[Tuple[int, date]]:
    """The workspace and month one platform invoice number is about, or ``None``.

    The inverse of ``invoice_number_for``, and the only way back: a platform
    invoice belongs to the management workspace, so its number is all that says
    which workspace it bills. ``None`` for anything that is not one of these
    numbers — an invoice a workspace issued to its own customers, or one typed in
    by hand — which is what keeps a reader from acting on someone else's bill.
    """
    if not (invoice_number or "").startswith(INVOICE_PREFIX):
        return None
    workspace, separator, period = invoice_number[len(INVOICE_PREFIX):].partition("-")
    if not separator or not workspace.isdigit() or len(period) != 6 or not period.isdigit():
        return None
    try:
        return int(workspace), date(int(period[:4]), int(period[4:]), 1)
    except ValueError:
        # A month outside 1 to 12: a number shaped like ours that nothing issued.
        return None


# ── Money ────────────────────────────────────────────────────────────


def _step(decimal_places: int) -> Decimal:
    return Decimal(1).scaleb(-decimal_places)


def round_to(amount: Decimal, decimal_places: int) -> Decimal:
    """``amount`` written to ``decimal_places``, rounding halves up.

    Public because the console estimates what a bill will come to and has to round
    it the way the bill itself will be rounded, rather than a way of its own.
    """
    return Decimal(amount).quantize(_step(decimal_places), rounding=ROUND_HALF_UP)


def _units(value: Decimal) -> str:
    """A quantity written the short way, for a line's description."""
    return format(Decimal(value).normalize(), "f")


# ── Issuing ──────────────────────────────────────────────────────────


def _previous_month(today: date) -> date:
    """A day in the month before ``today``'s."""
    return today.replace(day=1) - timedelta(days=1)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=datetime_timezone.utc)


def renewal_period_bounds(period_start: date) -> Tuple[datetime, datetime]:
    """The half-open range of period ends a bill for ``period_start``'s month covers.

    Which entitlements one month's bill charged for, written once: billing reads
    it to build the renewal lines, and renewing reads it to know which periods the
    payment bought another month of. The two cannot drift apart into a workspace
    being charged for something that is never renewed.
    """
    first, next_first = usage.month_bounds(period_start)
    return _midnight(first), _midnight(next_first)


def _tax_percent(country: str, platform_workspace) -> Decimal:
    """The percentage to add to the whole bill of a workspace selling in ``country``.

    The country rather than the workspace, because the answer depends on nothing
    else: one rate over the invoice, the same for every workspace in that country.

    Only New Zealand is worked out, at whatever rate the management workspace has
    recorded for it — GST is on everything a New Zealand deployment sells, so one
    rate over the invoice is the whole rule.

    **Unfinished.** Every other country is billed untaxed, which is right for some
    (a sale to a business in another country, reverse-charged there) and wrong for
    others, and neither this function nor the model has anywhere to record which.
    Before this deployment sells outside New Zealand, somewhere has to hold the
    customer's tax registration and the rule that follows from it.
    """
    from bfg.finance.models import TaxRate

    if country != GST_COUNTRY:
        return ZERO
    rate = (
        TaxRate.objects.filter(
            workspace=platform_workspace, country=GST_COUNTRY, is_active=True
        )
        .order_by("id")
        .values_list("rate", flat=True)
        .first()
    )
    if rate is None:
        logger.warning(
            "No active %s tax rate on the platform workspace; billing untaxed.", GST_COUNTRY
        )
        return ZERO
    return Decimal(rate)


def _currency(code: str, *, create: bool):
    from bfg.common.onboarding.provisioning import ensure_currency
    from bfg.finance.models import Currency

    row = Currency.objects.filter(code=code, is_active=True).first()
    if row is None and create:
        ensure_currency(code)
        row = Currency.objects.filter(code=code, is_active=True).first()
    return row


def _renewal_lines(entitlements, rate_for, currency_code: str, decimal_places: int) -> List[dict]:
    """One line for each entitlement whose period ended in the month being billed.

    An entitlement that was granted rather than bought is not charged for — that
    is what granting one means — and one that was bought without a plan has no
    price to charge, which is a hole in whatever sold it rather than something to
    guess at, so it is logged and left off.

    ``rate_for`` gives the rate between two currencies and is memoised by the
    caller, so a hundred renewals priced in the same currency are one rate lookup.
    """
    lines = []
    for row in sorted(entitlements, key=lambda item: (item.key, item.id)):
        if row.source == WorkspaceEntitlement.SOURCE_GRANTED:
            continue
        if row.plan is None:
            logger.warning(
                "Entitlement %s (workspace %s, key %r) was bought without a plan and cannot be priced.",
                row.id, row.workspace_id, row.key,
            )
            continue
        plan_currency = get_default_currency_for_workspace(row.plan.workspace)
        price = round_to(
            Decimal(row.plan.price) * rate_for(plan_currency, currency_code), decimal_places
        )
        what = row.key or "base plan"
        lines.append(
            {
                "description": f"{row.plan.name} — {what} renewal"[:255],
                "quantity": ONE,
                "unit_price": price,
                "subtotal": price,
            }
        )
    return lines


def _usage_lines(meters, rate: Decimal, decimal_places: int) -> List[dict]:
    """One line per meter: how many points it came to, at a point apiece.

    The quantity is the points rather than the calls, because that is what the
    price is per — a meter's calls can be tokens, and a token is not a unit anyone
    is charged a currency amount for. The calls are in the description, so a line
    can still be checked against what the workspace did.

    The amount is worked out from the published rate and only then rounded, while
    the unit price is that rate written to the places the currency has. The two
    therefore need not multiply out to the last cent on a line with a large
    quantity, and the invoice says which rate it was issued at so that every line
    can still be checked. Rounding the rate first instead would make each line
    multiply out exactly and charge up to half a cent per point too much or too
    little — a few dollars over a busy month, always in the same direction.
    """
    lines = []
    for meter, totals in sorted(meters.items()):
        points = Decimal(totals["points"]).quantize(POINT_PRECISION, rounding=ROUND_HALF_UP)
        if points <= ZERO:
            # Usage backed out in full, or less than a cent's worth over the whole
            # month: below the resolution an invoice is written at either way.
            continue
        lines.append(
            {
                "description": f"{meter} — {_units(totals['quantity'])} metered units"[:255],
                "quantity": points,
                "unit_price": round_to(rate, decimal_places),
                "subtotal": round_to(points * rate, decimal_places),
            }
        )
    return lines


def _trial_line(points: Decimal, rate: Decimal, chargeable: Decimal, decimal_places: int) -> Optional[dict]:
    """The credit a workspace's first bill gets, never more than the bill itself."""
    credit = min(round_to(points * rate, decimal_places), chargeable)
    if credit <= ZERO:
        return None
    return {
        "description": f"Trial credit ({_units(points)} points)",
        "quantity": ONE,
        "unit_price": -credit,
        "subtotal": -credit,
    }


def issue_monthly_bills(month=None, *, dry_run: bool = False) -> list:
    """Bill every workspace that used something, or has something to renew, in ``month``.

    ``month`` is any date inside the period to bill, the month before this one by
    default, which is what a run at the start of a month wants. One invoice per
    workspace, issued by the management workspace, made out to the workspace's
    owner and dated today; it falls due after the deployment's ``invoice_due_days``.

    Lines, in order: each entitlement whose period ended inside the month, priced
    at its plan; each meter the workspace ran up points on, at a point per US
    dollar converted to the workspace's currency at today's rate; and, once in a
    workspace's life, the deployment's trial credit, never more than the rest of
    the bill comes to. New Zealand workspaces are taxed over the whole invoice; see
    ``_tax_percent`` for what is still missing everywhere else.

    Bills are for what the month held, so an entitlement is billed for the month
    its period ended in whatever has become of it since — including one that has
    lapsed, and one whose row a sweep has already moved to ``ended``. Reading only
    the rows still live would make whether a month is billed depend on whether
    ``close_entitlement_periods`` happened to run first, which for a fortnight's
    grace would silently drop every period ending in the first half of a month.
    This does not itself write the next period: renewing is a purchase, and a bill
    is a record of one that was made.

    Called from the ``issue_monthly_bills`` management command. With ``dry_run``
    nothing at all is written — no invoice, no customer, no currency row, and the
    trial credit stays unspent — and the same list comes back, so a run can be read
    before it is made.

    Returns one entry per workspace considered, whether or not it was billed:
    ``skipped`` says why it was not. A workspace is skipped rather than failing the
    run when it has no owner to bill, no rate to convert at, or a bill for that
    month already — one workspace's problem should not cost every other workspace
    its invoice.

    Raises ``PlatformWorkspaceMissing`` when the deployment has no management
    workspace, since there is then nobody for the invoices to come from.
    """
    from bfg.common.models import Customer, Workspace
    from bfg.finance.models import Invoice, InvoiceItem

    platform_workspace = get_platform_workspace()
    if platform_workspace is None or not is_platform_workspace(platform_workspace):
        raise PlatformWorkspaceMissing(
            "PLATFORM_WORKSPACE_SLUG names no workspace, so there is nothing to issue bills from."
        )

    today = timezone.now().date()
    period_start, period_next = usage.month_bounds(
        month if month is not None else _previous_month(today)
    )
    due_date = today + timedelta(days=get_variable("invoice_due_days"))
    trial_points = Decimal(get_variable("trial_points"))

    # One query each, however many workspaces are being billed.
    metered = {}
    for row in (
        UsageRecord.all_objects.filter(day__gte=period_start, day__lt=period_next)
        .values("workspace_id", "meter")
        .annotate(quantity=Sum("quantity"), points=Sum("points"))
        .order_by("workspace_id", "meter")
    ):
        metered.setdefault(row["workspace_id"], {})[row["meter"]] = {
            "quantity": Decimal(row["quantity"] or 0),
            "points": Decimal(row["points"] or 0),
        }

    renewal_since, renewal_until = renewal_period_bounds(period_start)
    renewals = {}
    for row in (
        WorkspaceEntitlement.all_objects.filter(
            current_period_end__gte=renewal_since,
            current_period_end__lt=renewal_until,
        )
        .select_related("plan", "plan__workspace", "plan__workspace__workspace_settings")
        .order_by("workspace_id", "key", "id")
    ):
        renewals.setdefault(row.workspace_id, []).append(row)

    candidates = sorted(set(metered) | set(renewals))
    if not candidates:
        return []

    workspaces = {
        row.id: row
        for row in Workspace.objects.filter(id__in=candidates).select_related("workspace_settings")
    }
    owners = ownership.workspace_owners(candidates)
    profiles = {
        row.workspace_id: row
        for row in WorkspacePlatformProfile.objects.filter(workspace_id__in=candidates)
    }
    already_billed = set(
        Invoice.all_objects.filter(
            workspace=platform_workspace,
            invoice_number__in=[invoice_number_for(one, period_start) for one in candidates],
        ).values_list("invoice_number", flat=True)
    )

    results = []
    # Memoised across the whole run, so that what each of these costs is one query
    # per distinct currency, currency pair and country, rather than per workspace
    # and — for the renewals — per line.
    rates: dict = {}
    currencies: dict = {}
    percentages: dict = {}

    def rate_between(from_code: str, to_code: str):
        """One unit of ``from_code`` in ``to_code``, or ``None`` with no rate stored."""
        pair = (from_code, to_code)
        if pair not in rates:
            try:
                rates[pair] = exchange_rates.convert(ONE, from_code, to_code, on=today)
            except exchange_rates.ExchangeRateNotFound:
                rates[pair] = None
        return rates[pair]

    def currency_for(code: str):
        if code not in currencies:
            currencies[code] = _currency(code, create=not dry_run)
        return currencies[code]

    def percent_for(country: str):
        if country not in percentages:
            percentages[country] = _tax_percent(country, platform_workspace)
        return percentages[country]

    def rate_or_refuse(from_code: str, to_code: str) -> Decimal:
        """``rate_between``, raising rather than answering ``None``.

        What the lines want: a missing rate is this workspace's invoice skipped,
        and one ``except`` around building them says so once.
        """
        converted = rate_between(from_code, to_code)
        if converted is None:
            raise exchange_rates.ExchangeRateNotFound(
                f"No {from_code} to {to_code} rate had been stored by {today.isoformat()}.",
                details={"from": from_code, "to": to_code, "on": today.isoformat()},
            )
        return converted

    for workspace_id in candidates:
        workspace = workspaces.get(workspace_id)
        if workspace is None:
            continue  # Deleted between the queries above and this loop.

        number = invoice_number_for(workspace_id, period_start)
        currency_code = (get_default_currency_for_workspace(workspace) or POINT_CURRENCY).upper()
        entry = {
            "workspace": workspace_id,
            "workspace_name": workspace.name,
            "invoice_number": number,
            "period": f"{period_start:%Y-%m}",
            "currency": currency_code,
            "lines": [],
            "subtotal": ZERO,
            "tax": ZERO,
            "total": ZERO,
            "issued": False,
            "skipped": "",
        }

        if is_platform_workspace(workspace):
            entry["skipped"] = "the platform does not bill itself"
            results.append(entry)
            continue
        if number in already_billed:
            entry["skipped"] = "already billed for this period"
            results.append(entry)
            continue
        owner = owners.get(workspace_id)
        if owner is None:
            entry["skipped"] = "no owner to bill"
            results.append(entry)
            continue

        currency = currency_for(currency_code)
        if currency is None and not dry_run:
            entry["skipped"] = f"{currency_code} is not a currency this deployment has"
            results.append(entry)
            continue
        decimal_places = min(
            currency.decimal_places if currency is not None else ASSUMED_DECIMAL_PLACES,
            INVOICE_DECIMAL_PLACES,
        )

        rate = rate_between(POINT_CURRENCY, currency_code)
        if rate is None:
            entry["skipped"] = f"no {POINT_CURRENCY} to {currency_code} rate for {today.isoformat()}"
            results.append(entry)
            continue

        try:
            lines = _renewal_lines(
                renewals.get(workspace_id, ()), rate_or_refuse, currency_code, decimal_places
            )
        except exchange_rates.ExchangeRateNotFound as missing:
            entry["skipped"] = missing.message
            results.append(entry)
            continue
        lines += _usage_lines(metered.get(workspace_id, {}), rate, decimal_places)
        if not lines:
            entry["skipped"] = "nothing chargeable this period"
            results.append(entry)
            continue

        profile = profiles.get(workspace_id)
        credit = None
        if trial_points > ZERO and (profile is None or profile.trial_points_used_at is None):
            credit = _trial_line(
                trial_points, rate, sum(line["subtotal"] for line in lines), decimal_places
            )
            if credit is not None:
                lines.append(credit)

        percent = percent_for((get_default_country_for_workspace(workspace) or "").upper())
        for line in lines:
            # Per line rather than over the invoice, so that the tax column and the
            # lines under it add up to the same number by construction.
            line["tax"] = round_to(line["subtotal"] * percent / Decimal(100), decimal_places)
            line["tax_type"] = "default" if percent else "no_tax"

        entry["lines"] = lines
        entry["subtotal"] = sum((line["subtotal"] for line in lines), ZERO)
        entry["tax"] = sum((line["tax"] for line in lines), ZERO)
        entry["total"] = entry["subtotal"] + entry["tax"]

        if dry_run:
            results.append(entry)
            continue

        try:
            with transaction.atomic():
                customer, _ = Customer.all_objects.get_or_create(
                    workspace=platform_workspace, user=owner
                )
                invoice = Invoice.all_objects.create(
                    workspace=platform_workspace,
                    customer=customer,
                    invoice_number=number,
                    status=ISSUED_STATUS,
                    subtotal=entry["subtotal"],
                    tax=entry["tax"],
                    total=entry["total"],
                    currency=currency,
                    issue_date=today,
                    due_date=due_date,
                    notes=(
                        f"{workspace.name} (workspace {workspace_id}) — "
                        f"usage and renewals for {period_start:%Y-%m}. "
                        # The rate every line was worked out at, so that an invoice
                        # can be checked against the day's published rate years later.
                        f"1 {POINT_CURRENCY} = {rate:f} {currency_code} on {today.isoformat()}."
                    ),
                )
                InvoiceItem.objects.bulk_create(
                    [
                        InvoiceItem(
                            invoice=invoice,
                            description=line["description"],
                            quantity=line["quantity"],
                            unit_price=line["unit_price"],
                            subtotal=line["subtotal"],
                            tax=line["tax"],
                            tax_type=line["tax_type"],
                        )
                        for line in lines
                    ]
                )
                if credit is not None:
                    if profile is None:
                        profile, _ = WorkspacePlatformProfile.objects.get_or_create(
                            workspace=workspace
                        )
                    profile.trial_points_used_at = timezone.now()
                    profile.save(update_fields=["trial_points_used_at", "updated_at"])
        except IntegrityError:
            # The unique index on the number is what makes two runs at once safe,
            # rather than the check further up being trusted to have been the only
            # one. Which constraint objected is worth establishing, though: writing
            # an invoice also writes a customer, and reporting every clash as an
            # invoice already issued would let a workspace go unbilled for a month
            # with nothing in the output but a line saying all was well.
            if not Invoice.all_objects.filter(
                workspace=platform_workspace, invoice_number=number
            ).exists():
                raise
            entry["skipped"] = "already billed for this period"
            results.append(entry)
            continue

        entry["issued"] = True
        results.append(entry)

    return results


# ── What an unpaid bill stops ────────────────────────────────────────


def overdue_cache_key(workspace_id) -> str:
    """Where the answer to "does this workspace owe anything" is kept.

    One function rather than the string in both places that touch it: the reader
    and whatever has just made the answer wrong have to agree on it, and a key
    spelled twice is a key that eventually differs by a colon.
    """
    return f"platform:overdue:{workspace_id}"


def forget_overdue(workspace_id) -> None:
    """Throw away the cached answer for one workspace.

    Called by whatever has just changed it — a bill being paid — so that the next
    metered call asks the database instead of being refused for up to
    ``OVERDUE_CACHE_SECONDS`` on an answer from before the money arrived. The
    cache is there to keep a query off the path of every paid call, not to make a
    workspace wait a minute after it has settled up.
    """
    cache.delete(overdue_cache_key(workspace_id))


def has_overdue_invoice(workspace) -> bool:
    """Whether ``workspace`` has a platform invoice that is past due and unpaid.

    Asked before every metered call, through ``usage.may_meter``, so it is one
    indexed query and the answer is then reused for ``OVERDUE_CACHE_SECONDS``. A
    workspace that has just fallen overdue keeps spending for up to that long,
    which is worth it against a query on the path every paid call takes. The other
    direction is not left to expire: paying a bill drops the key through
    ``forget_overdue``, so a workspace is working again as soon as the money is.

    The invoice numbers are read by prefix because the number is the only thing
    tying a platform invoice to the workspace it is about — the invoice's own
    workspace is the management one. Which is also why only the management
    workspace's invoices are read: a workspace chooses its own invoice prefix
    (``finance.InvoiceSettings``), so one that set it to another workspace's
    platform prefix could otherwise stop that workspace's metered calls by leaving
    an invoice of its own unpaid. The extra condition is a join in the same query.

    Invoices that come to nothing are left out. A month covered entirely by the
    trial credit is still worth an invoice, for the record of what was used, but it
    is not a debt and must not stop a workspace working.
    """
    from django.conf import settings

    from bfg.finance.models import Invoice

    if workspace is None or workspace.pk is None:
        return False
    slug = getattr(settings, "PLATFORM_WORKSPACE_SLUG", "")
    if not slug:
        # Nothing issues platform invoices, so there are none to be behind on.
        return False

    cache_key = overdue_cache_key(workspace.pk)
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    overdue = Invoice.all_objects.filter(
        workspace__slug=slug,
        invoice_number__startswith=invoice_number_prefix(workspace.pk),
        status__in=UNPAID_STATUSES,
        due_date__lt=timezone.now().date(),
        total__gt=ZERO,
    ).exists()
    cache.set(cache_key, 1 if overdue else 0, OVERDUE_CACHE_SECONDS)
    return overdue

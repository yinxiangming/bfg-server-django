# -*- coding: utf-8 -*-
"""
Getting a workspace an add-on it does not have yet.

Renewing gives a workspace another period of something it already holds, and
granting hands one over for nothing; this is the third way an entitlement comes
about, and the only one a workspace can ask for itself. Without it an add-on could
only be had by an operator writing the row by hand.

**What an add-on costs is a plan.** A ``shop.SubscriptionPlan`` on the management
workspace stands for one thing the deployment sells, and its ``code`` says which:
the key of the add-on extension it prices, or ``PLAN_CODE_BASE_PLAN`` — the empty
string, the same one ``WorkspaceEntitlement.KEY_BASE_PLAN`` uses — for the base
plan itself. The plan's ``price`` is a month of it, in the management workspace's
own currency. An add-on no plan of that workspace names has not been priced on
this deployment, and nothing can be sold that has no price; leave no other plan of
the management workspace uncoded, since an uncoded one there reads as the base
plan. See ``docs/reference/server-switches.md``.

Two ways it can go, and the difference is the price rather than anything declared:

*Free* — the workspace is entitled at once, with no period end, and the extension
is switched on in the same transaction. Something a workspace has been told it has
must actually be there, so either both are written or neither is.

*Priced* — an invoice is issued and **nothing else is written**. An entitlement is
what the workspace has paid for, and it has not paid yet; the first period is
written when the bill is settled, by ``renewals``. A bill that has not been paid is
a debt like any other and stops metered calls once it falls due, which is
``has_overdue_invoice``'s doing and needs nothing here.

*Priced, but not billed yet* — the workspace is entitled for one period straight
away and no bill is written now. Two things lead here, and both are a bill that
cannot or should not be written today rather than a different price:

  A *trial*, when the plan carries ``trial_period_days`` and this workspace has
  never held the add-on. The period is the trial's length and it costs nothing,
  which is what a trial is.

  *No exchange rate*, when the plan's currency cannot be turned into the
  workspace's today. A rate that has not been read yet is the deployment's
  problem and it is not worth an hour of it to the workspace asking, so the add-on
  is switched on for a month and the month is charged for where every other month
  is — ``issue_monthly_bills``, which prices the period in the month it ends.

Either way the entitlement is a bought one with a plan and an end, so it is billed
and renewed by the same two functions every other purchased period is. What moves
is when the first bill is written, not whether one is.

Like the rest of the platform services this runs with no workspace bound to the
thread — the console's paths are public — so tenant-scoped models are read through
``all_objects`` and filtered by workspace by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from bfg.common.constants import (
    get_default_country_for_workspace,
    get_default_currency_for_workspace,
)
from bfg.common.extensions import registry, services as extension_services
from bfg.common.extensions.manifest import PRICING_ADDON
from bfg.core.exceptions import BFGException
from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.services import billing, entitlements, exchange_rates, ownership
from bfg.platform.services.platform_variables import get_variable
from bfg.platform.utils import get_platform_workspace

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")

#: The ``code`` of the plan that prices the base plan rather than an add-on.
PLAN_CODE_BASE_PLAN = WorkspaceEntitlement.KEY_BASE_PLAN

# Why an acquisition was refused. Stable for the console, which has something
# different to say about each.
ALREADY_ENTITLED = "already_entitled"
NOT_AN_ADDON = "not_an_addon"
NO_PLAN = "no_plan"
NO_OWNER = "no_owner"
UNKNOWN_CURRENCY = "unknown_currency"
KEY_TOO_LONG = "key_too_long"

# How long the first period runs when there was no rate to bill at. A month,
# because a month is what the plan's price buys and what renewing one buys again.
DEFERRED_MONTHS = 1

# How many numbers are tried before giving up. Only a second acquisition of the
# same add-on starting at the same moment can take the one this worked out, and
# the loser of that race takes the next; a third attempt is there so that the
# answer does not depend on two racing rather than three.
NUMBER_ATTEMPTS = 3


class AcquisitionRefused(BFGException):
    """An add-on that cannot be acquired as asked"""

    default_message = "This add-on cannot be acquired"
    default_code = "acquisition_refused"


@dataclass(frozen=True)
class Acquisition:
    """What came of asking for an add-on.

    Exactly one of the two is filled in: ``entitlement`` for one the workspace now
    has, and ``invoice`` for a priced one it has yet to pay for. ``invoice_is_new``
    is false when the workspace was already holding an unpaid bill for this add-on
    and was handed that one again rather than a second.

    An entitlement comes with a reason it was written before any money arrived, so
    that a console can say which it is. ``trial_days`` is how long a trial runs, and
    zero when this is not one; ``billed_later`` is true when there was no rate to
    write today's bill at and the period will be charged for by the monthly run.
    Neither is set for an add-on the deployment prices at nothing, which is not
    billed at all.
    """

    entitlement: Optional[WorkspaceEntitlement] = None
    invoice: object = None
    invoice_is_new: bool = True
    trial_days: int = 0
    billed_later: bool = False


def plan_for(key: str = PLAN_CODE_BASE_PLAN):
    """The management workspace's plan for ``key``, or ``None`` if nothing prices it.

    ``None`` also when the deployment has no management workspace, since there is
    then nowhere for a price to have been recorded. Should two of its plans carry
    the same code, which nothing prevents, the earliest is taken so that the answer
    does not depend on the order rows come back in.
    """
    from bfg.shop.models import SubscriptionPlan

    platform_workspace = get_platform_workspace()
    if platform_workspace is None:
        return None
    return (
        SubscriptionPlan.objects.filter(workspace=platform_workspace, code=key, is_active=True)
        .select_related("workspace", "workspace__workspace_settings")
        .order_by("id")
        .first()
    )


def acquire(workspace, key: str, *, user=None) -> Acquisition:
    """Get ``workspace`` the add-on ``key``, or bill it for one.

    A free add-on is entitled and switched on. A priced one is invoiced and left to
    be paid for — unless it comes with a trial the workspace has not had, or there
    is no rate to write today's bill at, in which cases it is entitled for a period
    and billed by the monthly run instead. Either way the answer says which
    happened, and the caller renders it — nothing here knows what a console shows.

    Raises ``AcquisitionRefused`` with a ``code`` for everything this can say no
    to: the extension is part of the base plan rather than something sold
    separately (``not_an_addon``), the workspace already has it
    (``already_entitled``), or the deployment has never priced it (``no_plan``). A
    priced one can also be refused for want of something a bill needs — an owner to
    make it out to (``no_owner``), a currency (``unknown_currency``) — and those are
    the deployment's to fix rather than the workspace's. ``extensions.ExtensionError``
    comes back from a key no app declares and from an activation the extension itself
    refused.
    """
    manifest = registry.get_manifest(key)
    if manifest is None:
        raise extension_services.ExtensionError(
            "unknown_extension", f"No extension named {key!r} is deployed."
        )
    if manifest.pricing != PRICING_ADDON:
        raise AcquisitionRefused(
            f"{key} is part of the base plan and is not acquired separately.", code=NOT_AN_ADDON
        )
    if entitlements.is_entitled(workspace, key):
        raise AcquisitionRefused(
            f"This workspace is already entitled to {key}.", code=ALREADY_ENTITLED
        )
    plan = plan_for(key)
    if plan is None:
        raise AcquisitionRefused(
            f"Nothing prices {key} on this deployment. Whoever runs it has to give the "
            f"management workspace a subscription plan whose code is {key!r} first.",
            code=NO_PLAN,
        )

    if Decimal(plan.price) <= ZERO:
        return Acquisition(entitlement=_entitle(workspace, key, plan, user))
    outstanding = _outstanding_invoice(workspace, key)
    if outstanding is not None:
        return Acquisition(invoice=outstanding, invoice_is_new=False)

    trial_days = _trial_days(plan, _has_held(workspace, key))
    if trial_days:
        now = timezone.now()
        return Acquisition(
            entitlement=_entitle(
                workspace,
                key,
                plan,
                user,
                starts_at=now,
                period_end=now + timedelta(days=trial_days),
            ),
            trial_days=trial_days,
        )

    try:
        return Acquisition(invoice=_issue_bill(workspace, key, plan))
    except exchange_rates.ExchangeRateNotFound as missing:
        # Not the workspace's fault and not worth its wait. The period is written
        # now and ``issue_monthly_bills`` charges for it in the month it ends, by
        # which time a refresh will almost certainly have run. A rate that stays
        # missing shows up there instead, as a workspace skipped by the run.
        logger.warning(
            "Workspace %s acquired %r without a bill: %s Its first month will be "
            "billed by the monthly run.",
            workspace.pk, key, missing.message,
        )
        now = timezone.now()
        return Acquisition(
            entitlement=_entitle(
                workspace,
                key,
                plan,
                user,
                starts_at=now,
                period_end=entitlements.add_months(now, DEFERRED_MONTHS),
            ),
            billed_later=True,
        )


def _trial_days(plan, already_held: bool) -> int:
    """How long a trial of ``plan`` runs, or zero when there is not one to have.

    Zero for a plan with no trial on it, and zero for a workspace that has held the
    add-on before: a trial is an introduction to something, and one that came round
    again every time an entitlement lapsed would be a way of never paying for it.

    One rule, two readers — acquiring writes the period from it, and ``price_list``
    tells a console what it would get — so what a workspace is shown and what it is
    given cannot drift apart.
    """
    days = int(plan.trial_period_days or 0)
    return 0 if already_held or days <= 0 else days


def _has_held(workspace, key: str) -> bool:
    """Whether ``workspace`` has ever held an entitlement to ``key``.

    Every row counts, whatever became of it — ended, granted, or paid for — since
    each of them is a time the workspace has had the add-on.
    """
    return WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key).exists()


def price_list(workspace) -> dict:
    """What each add-on this deployment sells would cost ``workspace``, by key.

    For a console listing extensions: one entry per plan of the management
    workspace that names an add-on, so a key nothing prices is simply absent and a
    deployment that sells nothing gets an empty answer. The base plan is left out —
    it is not an add-on anyone acquires here — as is every plan of a workspace's own.

    ``amount`` is the plan's price in the currency it is written in, and
    ``workspace_amount`` the same month converted into the workspace's own at
    today's rate — ``None`` when no rate has been stored for the pair, which is a
    price that can still be shown in the deployment's currency rather than one that
    cannot be shown at all. ``trial_days`` is what this workspace would actually
    get, so an add-on it has held before offers no second trial.

    Three queries however many add-ons there are: the plans, the keys the workspace
    has held, and one rate.
    """
    from bfg.shop.models import SubscriptionPlan

    platform_workspace = get_platform_workspace()
    if platform_workspace is None:
        return {}
    plans = list(
        SubscriptionPlan.objects.filter(workspace=platform_workspace, is_active=True)
        .exclude(code=PLAN_CODE_BASE_PLAN)
        .order_by("id")
    )
    if not plans:
        return {}

    held = set(
        WorkspaceEntitlement.all_objects.filter(workspace=workspace).values_list("key", flat=True)
    )
    plan_currency = (
        get_default_currency_for_workspace(platform_workspace) or billing.POINT_CURRENCY
    ).upper()
    currency_code = (get_default_currency_for_workspace(workspace) or billing.POINT_CURRENCY).upper()
    # Never created here: showing a page must not write a currency row the
    # deployment has not used, and a currency with no row is shown at the places
    # every invoice is written to anyway.
    currency = billing.currency_row(currency_code, create=False)
    places = min(
        currency.decimal_places if currency is not None else billing.ASSUMED_DECIMAL_PLACES,
        billing.INVOICE_DECIMAL_PLACES,
    )
    try:
        rate = exchange_rates.convert(ONE, plan_currency, currency_code, on=timezone.now().date())
    except exchange_rates.ExchangeRateNotFound:
        rate = None

    entries = {}
    for plan in plans:
        price = Decimal(plan.price)
        entries.setdefault(plan.code, {
            "plan": plan.name,
            "amount": f"{price}",
            "currency": plan_currency,
            "interval": plan.interval,
            "interval_count": plan.interval_count,
            "trial_days": _trial_days(plan, plan.code in held),
            "workspace_amount": (
                f"{billing.round_to(price * rate, places)}" if rate is not None else None
            ),
            "workspace_currency": currency_code,
        })
    return entries


# ── Free ─────────────────────────────────────────────────────────────


@transaction.atomic
def _entitle(
    workspace, key: str, plan, user, *, starts_at=None, period_end=None
) -> WorkspaceEntitlement:
    """Entitle ``workspace`` to ``key`` and switch the extension on.

    One transaction for both: an add-on that cannot be switched on — a prerequisite
    the workspace has not met, another extension it needs first — must not leave
    behind an entitlement to something it cannot use, and a workspace that has been
    told it has the add-on must not find the entitlement missing.

    ``period_end`` left out is an entitlement that does not expire, which is what a
    free add-on gets: there is nothing to renew, because it never falls due, is
    never billed for, and so has no payment to wait for. A trial and a period
    written ahead of its bill both pass one, along with the ``starts_at`` it was
    measured from, so that the row says a whole month rather than a month less the
    microseconds between working the end out and writing the row.

    Recorded as purchased either way, with the plan it came from, since it is
    something the workspace asked for at the price the deployment set — which for a
    free add-on happened to be nothing. Granting is the other source and means
    something else: an entitlement nobody asked for, which is never billed.
    """
    entitlement = WorkspaceEntitlement.all_objects.create(
        workspace=workspace,
        key=key,
        plan=plan,
        source=WorkspaceEntitlement.SOURCE_PURCHASED,
        starts_at=starts_at or timezone.now(),
        current_period_end=period_end,
        status=WorkspaceEntitlement.STATUS_ACTIVE,
    )
    extension_services.activate(workspace, key, user=user)
    return entitlement


# ── Priced ───────────────────────────────────────────────────────────


def _outstanding_invoice(workspace, key: str):
    """The unpaid bill ``workspace`` already has for ``key``, if it has one.

    Asking twice is one bill rather than two. The console cannot know whether the
    first request got through, and a second one is far more likely to be somebody
    wondering than somebody meaning to buy the add-on twice — which they could not
    do in any case, since one entitlement is all a key can hold at a time.

    A cancelled bill is not outstanding, and a paid one bought an entitlement that
    has since lapsed, so neither stands in the way of buying the add-on again.
    """
    from bfg.finance.models import Invoice

    platform_workspace = get_platform_workspace()
    if platform_workspace is None:
        return None
    return (
        Invoice.all_objects.filter(
            workspace=platform_workspace,
            invoice_number__startswith=billing.acquisition_number_prefix(workspace.pk, key),
            status__in=billing.UNPAID_STATUSES,
        )
        .select_related("currency")
        .prefetch_related("items")
        .order_by("-id")
        .first()
    )


def _issue_bill(workspace, key: str, plan):
    """Bill ``workspace``'s owner for a month of ``key``, and return the invoice.

    One line, at the plan's price converted into the workspace's own currency at
    today's rate, taxed by the rule every other platform bill is taxed by. It falls
    due after the deployment's ``invoice_due_days``, which is what eventually stops
    the workspace's metered calls if it is never paid.

    Raises ``exchange_rates.ExchangeRateNotFound`` when there is no rate to convert
    at, and ``AcquisitionRefused`` for the rest of what a bill needs and has not got.
    """
    from bfg.common.models import Customer
    from bfg.finance.models import Invoice, InvoiceItem

    platform_workspace = get_platform_workspace()
    owner = ownership.workspace_owners([workspace.pk]).get(workspace.pk)
    if owner is None:
        raise AcquisitionRefused(
            "This workspace has no owner to make the bill out to.", code=NO_OWNER
        )

    today = timezone.now().date()
    currency_code = (get_default_currency_for_workspace(workspace) or billing.POINT_CURRENCY).upper()
    currency = billing.currency_row(currency_code, create=True)
    if currency is None:
        raise AcquisitionRefused(
            f"{currency_code} is not a currency this deployment has.", code=UNKNOWN_CURRENCY
        )
    places = min(currency.decimal_places, billing.INVOICE_DECIMAL_PLACES)

    plan_currency = (
        get_default_currency_for_workspace(plan.workspace) or billing.POINT_CURRENCY
    ).upper()
    # ``ExchangeRateNotFound`` is deliberately let out: it is the one thing missing
    # here that the caller answers by writing the period anyway rather than by
    # refusing, so it must stay telling apart from the refusals around it.
    rate = exchange_rates.convert(ONE, plan_currency, currency_code, on=today)

    price = billing.round_to(Decimal(plan.price) * rate, places)
    percent = billing.tax_percent(
        (get_default_country_for_workspace(workspace) or "").upper(), platform_workspace
    )
    tax = billing.round_to(price * percent / Decimal(100), places)
    due_date = today + timedelta(days=get_variable("invoice_due_days"))
    what = key or "base plan"

    last_clash = None
    for _ in range(NUMBER_ATTEMPTS):
        number = _next_number(platform_workspace, workspace.pk, key)
        try:
            with transaction.atomic():
                customer, _ = Customer.all_objects.get_or_create(
                    workspace=platform_workspace, user=owner
                )
                invoice = Invoice.all_objects.create(
                    workspace=platform_workspace,
                    customer=customer,
                    invoice_number=number,
                    status=billing.ISSUED_STATUS,
                    subtotal=price,
                    tax=tax,
                    total=price + tax,
                    currency=currency,
                    issue_date=today,
                    due_date=due_date,
                    notes=(
                        f"{workspace.name} (workspace {workspace.pk}) — {what} acquired on "
                        f"{today.isoformat()}. "
                        # The rate the line was worked out at, so that the bill can
                        # be checked against the day's published rate years later.
                        f"1 {plan_currency} = {rate:f} {currency_code} on {today.isoformat()}."
                    ),
                )
                InvoiceItem.objects.create(
                    invoice=invoice,
                    description=f"{plan.name} — {what}, first month"[:255],
                    quantity=ONE,
                    unit_price=price,
                    subtotal=price,
                    tax=tax,
                    tax_type="default" if percent else "no_tax",
                )
            logger.info(
                "Workspace %s was billed %s for acquiring %r.", workspace.pk, number, key
            )
            return invoice
        except IntegrityError as clash:
            # The unique index on the number is what makes two requests at once
            # safe, rather than the count below being trusted to have been the only
            # one. The next attempt counts again and takes the number after.
            last_clash = clash
    raise last_clash


def _next_number(platform_workspace, workspace_id: int, key: str) -> str:
    """The number for the next bill ``workspace_id`` gets for ``key``.

    Counted from the numbers already used rather than kept anywhere: a workspace
    that buys an add-on, lets it lapse and buys it again needs a number it has not
    had before, and the bills themselves are the record of which those are.

    Refuses rather than truncating when the number will not fit the column, since a
    number that cannot be read back is a payment that would buy nothing.
    """
    from bfg.finance.models import Invoice

    prefix = billing.acquisition_number_prefix(workspace_id, key)
    used = Invoice.all_objects.filter(
        workspace=platform_workspace, invoice_number__startswith=prefix
    ).values_list("invoice_number", flat=True)
    highest = 0
    for number in used:
        tail = number[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))

    number = billing.acquisition_number(workspace_id, key, highest + 1)
    limit = Invoice._meta.get_field("invoice_number").max_length
    if len(number) > limit:
        raise AcquisitionRefused(
            f"{key} cannot be billed for: its bill would be numbered {number!r}, longer than "
            f"the {limit} characters an invoice number holds. The extension needs a shorter key.",
            code=KEY_TOO_LONG,
        )
    return number


# ── Plan packs ───────────────────────────────────────────────────────


def pack_obtain(workspace, manifest) -> bool:
    """``BFG_EXTENSION_PACK_OBTAIN`` for a deployment that sells extensions.

    Applying a plan pack stops at an add-on the workspace is not entitled to. For
    one that costs nothing that is a poor answer — nobody is being sold anything,
    and the pack exists precisely to say which of these a shop like this one
    should have — so it is obtained here and the pack carries on.

    An add-on with a price is **not** obtained: a pack is not a purchase, and
    nothing here may commit a workspace to a bill it has not been shown. Those stay
    skipped, which is what puts them in front of somebody as a thing to buy.

    Returns whether the workspace may now have it. ``acquire`` switches a free
    add-on on as part of entitling it, so a true answer usually means the pack has
    nothing left to do for that key.
    """
    plan = plan_for(manifest.key)
    if plan is None or Decimal(plan.price) > ZERO:
        return False
    try:
        acquire(workspace, manifest.key)
    except (AcquisitionRefused, extension_services.ExtensionError):
        # Refused for a reason the pack will report on its own next attempt.
        return False
    return True

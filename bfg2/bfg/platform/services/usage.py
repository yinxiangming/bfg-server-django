# -*- coding: utf-8 -*-
"""
Counting what a workspace uses, and deciding when it has used enough.

Usage is recorded after the fact, one row per workspace, meter, UTC day and price
version; the daily row is incremented in the database rather than read and written
back, so concurrent calls cannot lose each other's counts.

Everything here reads ``all_objects`` and filters by workspace by hand. Usage is
recorded from Celery tasks and totalled by platform billing, neither of which has
a workspace bound to the thread, and the scoped manager would answer both with
nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from typing import List, Tuple

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from bfg.platform.models.metering import UsageRecord
from bfg.platform.services import pricing
from bfg.platform.services.platform_variables import get_variable

ZERO = Decimal("0")


@dataclass(frozen=True)
class Allowance:
    """What a workspace has used this month against what it may use."""

    used: Decimal
    cap: Decimal
    remaining: Decimal


def _as_decimal(value) -> Decimal:
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _utc_day(moment) -> date:
    """The UTC date ``moment`` falls on; a naive datetime is read as UTC."""
    if timezone.is_naive(moment):
        moment = moment.replace(tzinfo=datetime_timezone.utc)
    return moment.astimezone(datetime_timezone.utc).date()


def month_bounds(month=None) -> Tuple[date, date]:
    """First day of ``month`` and first day of the month after it, both UTC.

    ``month`` is any date or datetime inside the month; the current UTC month by
    default. The second date is exclusive, which is what a ``day__lt`` filter wants.
    """
    if month is None:
        month = timezone.now()
    day = _utc_day(month) if isinstance(month, datetime) else month
    first = day.replace(day=1)
    # Day 28 is in every month, so a month's length never has to be worked out.
    next_first = (first + timedelta(days=32)).replace(day=1)
    return first, next_first


@transaction.atomic
def record_usage(workspace, meter: str, quantity=1, *, at=None) -> UsageRecord:
    """Add ``quantity`` of ``meter`` to ``workspace``'s usage and return the day's row.

    Called once a metered call has succeeded — never before, so a failed vendor
    call is not billed. Points are worked out at the price in force at ``at``
    (default now) and the row remembers which price that was, so a price change
    mid-day leaves the earlier calls priced as they were. A negative ``quantity``
    backs out usage recorded in error.

    Raises ``pricing.MeterNotPriced`` when the meter has no price; callers that
    must not fail go through ``bfg.platform.metering.meter`` instead.
    """
    moment = at or timezone.now()
    price = pricing.price_for(meter, at=moment)
    amount = Decimal(str(quantity))
    points = pricing.points_for(meter, amount, price=price)

    record, created = UsageRecord.all_objects.get_or_create(
        workspace=workspace,
        meter=meter,
        day=_utc_day(moment),
        price=price,
        defaults={"quantity": amount, "points": points},
    )
    if created:
        return record

    # F() rather than record.quantity += : two requests metering the same day at
    # the same time would otherwise each write the total they had read.
    UsageRecord.all_objects.filter(pk=record.pk).update(
        quantity=F("quantity") + amount,
        points=F("points") + points,
        # auto_now does not fire for a queryset update.
        updated_at=timezone.now(),
    )
    record.refresh_from_db()
    return record


def points_used(workspace, *, month=None) -> Decimal:
    """Points ``workspace`` has run up in ``month`` (the current UTC month by default)."""
    first, next_first = month_bounds(month)
    total = (
        UsageRecord.all_objects.filter(workspace=workspace, day__gte=first, day__lt=next_first)
        .aggregate(total=Sum("points"))["total"]
    )
    return _as_decimal(total)


def usage_by_day(workspace, *, month=None) -> List[dict]:
    """``workspace``'s usage in ``month``, one entry per day and meter.

    For a usage page and for the lines of an invoice: price versions are summed
    together, since which version applied is an explanation, not a line item.
    """
    first, next_first = month_bounds(month)
    rows = (
        UsageRecord.all_objects.filter(workspace=workspace, day__gte=first, day__lt=next_first)
        .values("day", "meter")
        .annotate(quantity=Sum("quantity"), points=Sum("points"))
        .order_by("day", "meter")
    )
    return [
        {
            "day": row["day"],
            "meter": row["meter"],
            "quantity": _as_decimal(row["quantity"]),
            "points": _as_decimal(row["points"]),
        }
        for row in rows
    ]


def monthly_cap(workspace) -> Decimal:
    """Points ``workspace`` may run up in a month.

    Its own cap when it has negotiated one, and the deployment's default otherwise.
    """
    profile = getattr(workspace, "platform_profile", None)
    cap = getattr(profile, "monthly_usage_cap_points", None) if profile is not None else None
    if cap is None:
        cap = get_variable("monthly_usage_cap_points")
    return _as_decimal(cap)


def allowance(workspace, *, month=None) -> Allowance:
    """What ``workspace`` has used this month, its cap, and what is left.

    ``remaining`` never goes below zero: usage can overshoot a cap, because a call
    is metered after it has already been made, and "how far over" is not something
    a caller should have to guard against.
    """
    used = points_used(workspace, month=month)
    cap = monthly_cap(workspace)
    return Allowance(used=used, cap=cap, remaining=max(cap - used, ZERO))


def may_meter(workspace, *, month=None) -> bool:
    """Whether ``workspace`` may make another metered call this month.

    Asked before a paid call is made, not after. Two things stop it: a platform
    invoice that is past due and unpaid, and this month's usage cap. Only metered
    calls are stopped — a workspace behind on its bill keeps its shop, its orders
    and its data, and loses the things that cost the deployment money on its
    behalf.

    The overdue answer is cached for a minute (``billing.OVERDUE_CACHE_SECONDS``),
    so the common path is the one usage query it always was.

    Raises whatever the database raises: a caller must not be told a workspace may
    spend because the question could not be answered.
    """
    # Imported here rather than at the top of the module: billing reads usage, and
    # a module-level import each way would not resolve. After the first call this
    # is a dictionary lookup, which is nothing against the query below it.
    from bfg.platform.services import billing

    if billing.has_overdue_invoice(workspace):
        return False
    return allowance(workspace, month=month).remaining > ZERO

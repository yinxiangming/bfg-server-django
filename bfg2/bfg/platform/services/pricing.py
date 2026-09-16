# -*- coding: utf-8 -*-
"""
What a metered call costs in points.

One point is one US dollar. A meter's price is whichever ``MeterPrice`` row was
effective at the moment being priced, so recording usage for yesterday prices it
at yesterday's rate even if the vendor has since put its price up.

A meter with no price at all is a deployment that has started selling something it
never priced. That raises rather than counting as zero: silently free usage is the
kind of mistake nobody notices until the month is over.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from bfg.core.exceptions import BFGException
from bfg.platform.models.metering import MeterPrice
from bfg.platform.services.platform_variables import get_variable

# Points are stored to eight decimal places, so a single call can cost as little as
# a millionth of a cent without rounding away to nothing.
POINT_PRECISION = Decimal("0.00000001")


class MeterNotPriced(BFGException):
    """A meter nothing has priced yet"""

    default_message = "This meter has no price"
    default_code = "meter_not_priced"


class InvalidMeterPrice(BFGException):
    """A price the columns cannot hold"""

    default_message = "Invalid meter price"
    default_code = "invalid_meter_price"


def price_for(meter: str, at=None) -> MeterPrice:
    """The price in force for ``meter`` at ``at`` (default now).

    Raises ``MeterNotPriced`` when no price had taken effect by then — including
    when prices exist but all of them start later, which is what a price entered
    with the wrong date looks like.
    """
    moment = at or timezone.now()
    price = (
        MeterPrice.objects.filter(meter=meter, effective_from__lte=moment)
        .order_by("-effective_from", "-id")
        .first()
    )
    if price is None:
        raise MeterNotPriced(
            f"No price for meter {meter!r} was in force at {moment.isoformat()}.",
            details={"meter": meter, "at": moment.isoformat()},
        )
    return price


def add_price(
    meter: str,
    *,
    vendor_cost,
    unit_size,
    margin=None,
    effective_from=None,
) -> MeterPrice:
    """Price ``meter`` from ``effective_from`` on (default now), and return the row.

    The only way a price is written. Prices are never edited: a vendor's new rate
    is another row with a later moment, so a bill already calculated can still be
    explained by the row it was calculated from. Nothing here updates or deletes,
    and neither should any caller.

    A row dated in the past does not reprice usage already recorded — every usage
    row keeps the price it was calculated with — but it does decide what usage
    recorded from now on for a day back then will cost, which is how a rate the
    vendor applied from the first of the month is entered after the fact. A row
    dated behind one that already exists changes nothing today; ``price_for`` says
    which row is in force.

    Raises ``InvalidMeterPrice``, carrying the column that refused it in
    ``details``, for anything the columns cannot hold — and for a cost or a
    margin below zero, which they would hold and nothing should: a negative price
    pays a workspace to use the deployment, and it is a mistyped minus far more
    often than it is a decision.
    """
    for field, value in (("vendor_cost", vendor_cost), ("margin", margin)):
        if value is None:
            continue
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
        except (ArithmeticError, TypeError, ValueError):
            # Not a number at all; the column says so in better words below.
            continue
        if number.is_finite() and number < 0:
            raise InvalidMeterPrice(
                f"{field}: this cannot be negative.",
                details={"field": field, "fields": {field: ["This cannot be negative."]}},
            )

    price = MeterPrice(
        meter=(meter or "").strip(),
        vendor_cost=vendor_cost,
        unit_size=unit_size,
        margin=margin,
        effective_from=effective_from or timezone.now(),
    )
    try:
        # The columns' own limits rather than a second copy of them here, so that a
        # number too big for one is refused in words instead of failing, or quietly
        # rounding, in the database.
        price.full_clean()
    except DjangoValidationError as invalid:
        problems = invalid.message_dict
        field = next(iter(problems))
        raise InvalidMeterPrice(
            " ".join(f"{name}: {' '.join(messages)}" for name, messages in problems.items()),
            details={"field": field, "fields": {name: list(messages) for name, messages in problems.items()}},
        ) from None
    price.save()
    return price


def points_for(meter: str, quantity, at=None, *, price: Optional[MeterPrice] = None) -> Decimal:
    """What ``quantity`` of ``meter`` comes to in points at ``at`` (default now).

    ``price`` skips the lookup for a caller that has already resolved the row —
    recording usage does, because it stores which price it used.
    """
    price = price or price_for(meter, at=at)
    per_unit = price.points_per_unit(get_variable("usage_margin"))
    return (per_unit * Decimal(str(quantity))).quantize(POINT_PRECISION, rounding=ROUND_HALF_UP)

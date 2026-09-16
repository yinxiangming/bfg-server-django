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


def points_for(meter: str, quantity, at=None, *, price: Optional[MeterPrice] = None) -> Decimal:
    """What ``quantity`` of ``meter`` comes to in points at ``at`` (default now).

    ``price`` skips the lookup for a caller that has already resolved the row —
    recording usage does, because it stores which price it used.
    """
    price = price or price_for(meter, at=at)
    per_unit = price.points_per_unit(get_variable("usage_margin"))
    return (per_unit * Decimal(str(quantity))).quantize(POINT_PRECISION, rounding=ROUND_HALF_UP)

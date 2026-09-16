# -*- coding: utf-8 -*-
"""
Keeping ``finance.ExchangeRate`` filled in, and reading a conversion out of it.

Bills are calculated in points — one point is one US dollar — and presented to a
workspace in its own currency, so a rate has to exist for the day a bill is
issued. The rates come from the European Central Bank's daily reference rates,
read through Frankfurter, which is free and needs no key.

Rates are stored, never fetched on demand: an invoice issued last March has to
keep explaining itself, and a conversion that reached the network would make
billing depend on a third party being up at the moment someone opens a page.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

import requests
from django.utils import timezone
from django.utils.dateparse import parse_date

from bfg.core.exceptions import BFGException

logger = logging.getLogger(__name__)

# The ECB's reference rates, served without a key or a quota.
RATES_URL = "https://api.frankfurter.dev/v1/latest"
# Short: this runs from a scheduled command with nothing waiting on it, and a
# refresh that hangs is worse than one that fails and is retried tomorrow.
HTTP_TIMEOUT_SECONDS = 10
# ``ExchangeRate.rate`` holds six decimal places.
RATE_PRECISION = Decimal("0.000001")


class ExchangeRateNotFound(BFGException):
    """No rate for a pair on or before the day asked about"""

    default_message = "No exchange rate for this pair"
    default_code = "exchange_rate_not_found"


def _as_day(value) -> date:
    """``value`` as a date; ``None`` is today, and a datetime is the day it falls on."""
    if value is None:
        return timezone.now().date()
    if isinstance(value, datetime):
        return value.date()
    return value


def _currency(code: str):
    """The active ``Currency`` row for ``code``.

    Created from the library's own currency profile when the deployment has never
    used that currency, because a rate with nothing to hang it off cannot be stored.
    """
    from bfg.common.onboarding.provisioning import ensure_currency
    from bfg.finance.models import Currency

    code = (code or "").strip().upper()
    row = Currency.objects.filter(code=code, is_active=True).first()
    if row is not None:
        return row
    ensure_currency(code)
    return Currency.objects.filter(code=code, is_active=True).first()


def _wanted_symbols(base: str, symbols: Optional[Iterable[str]]) -> list:
    """Which currencies to keep a rate for, with the base itself left out."""
    from bfg.finance.models import Currency

    if symbols is None:
        codes = set(Currency.objects.filter(is_active=True).values_list("code", flat=True))
    else:
        codes = {str(code).strip().upper() for code in symbols if str(code).strip()}
    return sorted(codes - {base})


def _fetch(base: str) -> Optional[dict]:
    """Every rate the service publishes against ``base``, or ``None``.

    The currencies wanted are deliberately *not* asked for. The service refuses a
    request naming a currency it does not publish, and a deployment that has one
    such currency on its books would then get no rates at all — every workspace
    unbillable because of one row nobody reads. Asking for everything is one small
    response, and what is not wanted is dropped here instead.

    Every way this can go wrong — a timeout, a 500, a body that is not JSON — is
    one thing to the caller: no rates today.
    """
    try:
        response = requests.get(
            RATES_URL,
            params={"base": base},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.exception("Could not read exchange rates from %s", RATES_URL)
        return None
    if not isinstance(payload, dict):
        logger.warning("Exchange rates from %s were not an object: %r", RATES_URL, payload)
        return None
    return payload


def refresh_rates(base: str = "USD", symbols: Optional[Iterable[str]] = None) -> int:
    """Read today's reference rates and store them, returning how many were written.

    Called from the ``refresh_exchange_rates`` management command, ideally once a
    day before bills are issued. ``symbols`` is which currencies to read; left out,
    it is every active currency the deployment has, because a rate for one it does
    not use is a row nothing will ever read.

    Nothing is raised at the caller: a refresh that fails leaves yesterday's rates
    in place, which is a better answer than a command that exits non-zero every
    time the network is slow. The failure is logged and the count comes back as
    zero, so a caller that cares can still tell.

    Rates are stored under the day the ECB published them rather than the day they
    were read, so a refresh run over a weekend rewrites Friday's row instead of
    inventing a Saturday rate the bank never set. A day already stored is updated
    rather than duplicated. A currency the bank does not publish is named in the
    log and skipped, rather than costing the refresh every other currency.
    """
    from bfg.finance.models import ExchangeRate

    base = (base or "").strip().upper()
    wanted = _wanted_symbols(base, symbols)
    if not wanted:
        logger.info("No currencies to read exchange rates for, against %s.", base)
        return 0

    payload = _fetch(base)
    if payload is None:
        return 0

    published = payload.get("rates") or {}
    rates = {code: published[code] for code in wanted if code in published}
    missing = sorted(set(wanted) - set(published))
    if missing:
        logger.warning(
            "No reference rate is published for %s against %s; nothing will be billed "
            "in those currencies until one is entered by hand.",
            ", ".join(missing), base,
        )

    day = parse_date(str(payload.get("date") or "")) or timezone.now().date()
    from_currency = _currency(base)
    if from_currency is None:
        logger.warning("Cannot store exchange rates: %s is not a currency.", base)
        return 0

    written = 0
    for code, value in sorted(rates.items()):
        to_currency = _currency(code)
        if to_currency is None:
            continue
        try:
            # ``Decimal(str(value))`` rather than ``Decimal(value)``: the rate
            # arrives from JSON as a float, and its shortest representation is the
            # number the bank published.
            rate = Decimal(str(value)).quantize(RATE_PRECISION, rounding=ROUND_HALF_UP)
        except (ArithmeticError, ValueError):
            logger.warning("Ignoring unusable rate %r for %s/%s.", value, base, code)
            continue
        ExchangeRate.objects.update_or_create(
            from_currency=from_currency,
            to_currency=to_currency,
            effective_date=day,
            defaults={"rate": rate},
        )
        written += 1

    logger.info("Stored %s exchange rates against %s for %s.", written, base, day)
    return written


def convert(amount, from_code: str, to_code: str, on=None) -> Decimal:
    """``amount`` in ``from_code`` expressed in ``to_code``, at the rate for ``on``.

    Called wherever a bill crosses currencies: points are US dollars and an invoice
    is in the workspace's own currency. ``on`` is the day whose rate to use, today
    by default; the latest rate stored on or before that day applies, so a bill
    issued on a Sunday uses Friday's published rate rather than failing.

    The result is not rounded — the caller knows how many decimal places the
    currency it is writing has, and rounding twice on the way to a line item loses
    a cent.

    Raises ``ExchangeRateNotFound`` when no rate for the pair had been stored by
    then. That is deliberate: a bill calculated at a made-up rate, or silently at
    one to one, is worse than one that waits until someone has run
    ``refresh_exchange_rates``.
    """
    from bfg.finance.models import ExchangeRate

    amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    from_code = (from_code or "").strip().upper()
    to_code = (to_code or "").strip().upper()
    if from_code == to_code:
        return amount

    day = _as_day(on)
    rate = (
        ExchangeRate.objects.filter(
            from_currency__code=from_code,
            to_currency__code=to_code,
            effective_date__lte=day,
        )
        .order_by("-effective_date", "-id")
        .values_list("rate", flat=True)
        .first()
    )
    if rate is None:
        # The inverse rate is not used to make one up. Dividing by the rate the
        # other way round gives a number the bank never published, and an invoice
        # has to be explainable by pointing at the row it was calculated from.
        raise ExchangeRateNotFound(
            f"No {from_code} to {to_code} rate had been stored by {day.isoformat()}.",
            details={"from": from_code, "to": to_code, "on": day.isoformat()},
        )
    return amount * Decimal(rate)

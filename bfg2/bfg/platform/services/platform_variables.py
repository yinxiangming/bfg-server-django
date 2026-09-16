# -*- coding: utf-8 -*-
"""
Reading and changing the deployment's platform variables.

Every number a deployment might want to tune without a release is declared here
with its default, so ``VARIABLES`` is the whole list of what can be set — a key
that is not in it is a typo, not a new setting, and is refused. Callers ask for
one variable at a time and get a ``Decimal``, an ``int`` or a ``bool``; the JSON
the column holds never leaves this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from django.core.cache import cache
from django.db import transaction

from bfg.core.exceptions import BFGException
from bfg.platform.models.variables import PlatformVariable, PlatformVariableChange

logger = logging.getLogger(__name__)

KIND_DECIMAL = "decimal"
KIND_INT = "int"
KIND_BOOL = "bool"

# Long enough that a metered call is not a query, short enough that an operator
# correcting a margin does not have to wait: these numbers decide what customers
# are charged. Workers that do not share a cache disagree for at most this long.
CACHE_SECONDS = 60


class UnknownPlatformVariable(BFGException):
    """A variable this deployment does not define"""

    default_message = "Unknown platform variable"
    default_code = "unknown_platform_variable"


class InvalidPlatformVariable(BFGException):
    """A value the variable cannot hold"""

    default_message = "Invalid platform variable value"
    default_code = "invalid_platform_variable"


@dataclass(frozen=True)
class VariableSpec:
    """One variable's type, default and meaning."""

    key: str
    kind: str
    default: Any
    description: str


VARIABLES: Dict[str, VariableSpec] = {
    spec.key: spec
    for spec in (
        VariableSpec(
            key="usage_margin",
            kind=KIND_DECIMAL,
            default=Decimal("0.30"),
            description="Share added on top of a vendor cost when a meter names no margin of its own.",
        ),
        VariableSpec(
            key="yearly_discount",
            kind=KIND_DECIMAL,
            default=Decimal("0.10"),
            description="Share taken off a year paid up front, against twelve months of the same plan.",
        ),
        VariableSpec(
            key="grace_days",
            kind=KIND_INT,
            default=14,
            description="Days a plan or add-on keeps working after its period ends unpaid.",
        ),
        VariableSpec(
            key="archive_after_days",
            kind=KIND_INT,
            default=30,
            description="Days an unused extension's data is kept live before it is archived.",
        ),
        VariableSpec(
            key="archive_retention_days",
            kind=KIND_INT,
            default=365,
            description="Days an archive is kept before it may be deleted.",
        ),
        VariableSpec(
            key="monthly_usage_cap_points",
            kind=KIND_DECIMAL,
            default=Decimal("20"),
            description="Points of metered usage a workspace with no cap of its own may run up in a month.",
        ),
        VariableSpec(
            key="trial_points",
            kind=KIND_DECIMAL,
            default=Decimal("1"),
            description="Points a new workspace starts with.",
        ),
        VariableSpec(
            key="invoice_due_days",
            kind=KIND_INT,
            default=14,
            description="Days a workspace has to pay an invoice before it counts as overdue.",
        ),
    )
}


def _spec(key: str) -> VariableSpec:
    spec = VARIABLES.get(key)
    if spec is None:
        raise UnknownPlatformVariable(
            f"No platform variable named {key!r}.", details={"key": key}
        )
    return spec


def _cache_key(key: str) -> str:
    return f"platform:variable:{key}"


def _coerce(spec: VariableSpec, value: Any) -> Any:
    """Turn a stored or supplied value into the type the spec promises.

    ``Decimal(str(value))`` rather than ``Decimal(value)`` because a JSON number
    arrives as a float, and going through its shortest representation keeps
    ``0.3`` from becoming ``0.29999999999999998``.
    """
    if spec.kind == KIND_BOOL:
        if not isinstance(value, bool):
            raise InvalidPlatformVariable(
                f"{spec.key} is a true/false value.", details={"key": spec.key, "value": value}
            )
        return value
    # ``isinstance(True, int)`` is true in Python, and silently charging a margin
    # of 1 because someone passed ``True`` is worse than refusing it.
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise InvalidPlatformVariable(
            f"{spec.key} is a number.", details={"key": spec.key, "value": value}
        )
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise InvalidPlatformVariable(
            f"{spec.key} is a number.", details={"key": spec.key, "value": value}
        )
    if number < 0:
        raise InvalidPlatformVariable(
            f"{spec.key} cannot be negative.", details={"key": spec.key, "value": value}
        )
    if spec.kind == KIND_INT:
        if number != number.to_integral_value():
            raise InvalidPlatformVariable(
                f"{spec.key} is a whole number.", details={"key": spec.key, "value": value}
            )
        return int(number)
    return number


def _to_json(spec: VariableSpec, value: Any) -> Any:
    """The JSON number or boolean to store for an already-coerced value."""
    if spec.kind == KIND_BOOL:
        return bool(value)
    if spec.kind == KIND_INT:
        return int(value)
    return float(value)


def get_variable(key: str) -> Any:
    """The value in force for ``key``, or its default when nothing has overridden it.

    Called wherever a price, a grace period or a cap is worked out, including on
    metered calls, so the answer is cached for ``CACHE_SECONDS``.
    """
    spec = _spec(key)
    cache_key = _cache_key(key)
    cached = cache.get(cache_key)
    if cached is not None:
        return _coerce(spec, cached)

    row = PlatformVariable.objects.filter(key=key).values_list("value", flat=True).first()
    stored = spec.default if row is None else row
    try:
        value = _coerce(spec, stored)
    except InvalidPlatformVariable:
        # A row written before the spec changed type, or by hand. The default is
        # the only value known to be usable, and billing must not stop for this.
        logger.exception("Platform variable %s holds %r, which it cannot be; using the default", key, stored)
        value = _coerce(spec, spec.default)
    cache.set(cache_key, _to_json(spec, value), CACHE_SECONDS)
    return value


def all_variables() -> Dict[str, Any]:
    """Every known variable and the value in force for it, for the console."""
    return {key: get_variable(key) for key in sorted(VARIABLES)}


@transaction.atomic
def set_variable(key: str, value: Any, *, user, reason: str = "") -> Any:
    """Override ``key`` and record who did it, returning the stored value.

    For an operator changing a number through the platform console, never for
    code: a caller that wants a different default should change the spec. The
    change record keeps the value that was in force, which is the default when
    the variable had never been overridden.
    """
    spec = _spec(key)
    coerced = _coerce(spec, value)
    stored = _to_json(spec, coerced)

    variable = (
        PlatformVariable.objects.select_for_update().filter(key=key).first()
        or PlatformVariable(key=key, value=_to_json(spec, spec.default))
    )
    old_value = variable.value
    variable.value = stored
    variable.updated_by = user if getattr(user, "is_authenticated", False) else None
    variable.save()

    PlatformVariableChange.objects.create(
        variable=variable,
        old_value=old_value,
        new_value=stored,
        changed_by=variable.updated_by,
        reason=reason,
    )
    # Twice: now, so this process stops serving the old value immediately, and
    # again after the commit, in case a concurrent reader refilled the entry from
    # the row as it still was.
    cache.delete(_cache_key(key))
    transaction.on_commit(lambda: cache.delete(_cache_key(key)))
    return coerced

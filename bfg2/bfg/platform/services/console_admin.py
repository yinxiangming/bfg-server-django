# -*- coding: utf-8 -*-
"""
What the console shows the people who run the deployment, as opposed to one workspace.

The console proper (``console_service``, ``console_billing``) is shared by platform
administrators and workspace owners, and everything in it is about one workspace.
This is the other half, and it is for platform administrators alone: the numbers
the whole deployment is billed by — what a variable is set to, what a meter costs,
what a currency was worth on a day — and the two things a platform administrator
decides for a single workspace that its owner may not, its monthly usage cap and
an entitlement given rather than sold.

Every report is worked out here rather than in the view, so that the shapes the
console is written against are one thing to read and one thing to test; the views
in ``console_admin_views`` check who is asking, read the request and call these.

Numbers that money is worked out from are strings rather than JSON numbers, for
the reason ``console_billing`` gives: JSON has no decimal, and a console that adds
up a column of floats gets a total that is a cent out. Whole numbers and
true/false are themselves.

Platform endpoints bind no workspace to the request, so tenant-scoped models are
read through ``all_objects`` here and filtered by workspace by hand.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.db.models import Max

from bfg.common.extensions import registry
from bfg.common.extensions.endpoints import user_summary
from bfg.core.exceptions import BFGException
from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.models.metering import MeterPrice
from bfg.platform.models.variables import PlatformVariable, PlatformVariableChange
from bfg.platform.models.workspace_profile import WorkspacePlatformProfile
from bfg.platform.services import entitlements, exchange_rates, pricing, usage
from bfg.platform.services import platform_variables as variables

logger = logging.getLogger(__name__)

UNKNOWN_EXTENSION = "unknown_extension"

# The scale every usage cap is written to: the column's, so that the deployment's
# default and a workspace's own read the same way.
_CAP_SCALE = Decimal(1).scaleb(
    -WorkspacePlatformProfile._meta.get_field("monthly_usage_cap_points").decimal_places
)

# How many stored rates the console is given at once, and the most it may ask for.
# Rates are one row per currency per day, so a deployment billing in four
# currencies fills the default in a fortnight; the cap is what stops a console
# page asking for every rate the deployment has ever stored.
RATES_DEFAULT_LIMIT = 50
RATES_MAX_LIMIT = 200


class AlreadyEntitled(BFGException):
    """A workspace that already holds a live entitlement to the key being granted"""

    default_message = "This workspace is already entitled to that"
    default_code = "already_entitled"


def _number(value) -> Optional[str]:
    """A Decimal as the string the console is given, or ``None`` left as it is.

    The rule ``console_billing`` applies to money, applied here to everything
    money is worked out from: margins, prices, caps and rates are all read back
    into arithmetic, and a float would round one of them on the way.
    """
    if value is None:
        return None
    return format(Decimal(value), "f")


def _moment(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


# ── Platform variables ───────────────────────────────────────────────


def _variable_value(spec, value):
    """One variable's value as the console is given it, by the kind it is declared as."""
    if spec.kind == variables.KIND_BOOL:
        return bool(value)
    if spec.kind == variables.KIND_INT:
        return int(value)
    return _number(Decimal(str(value)))


def _stored_value(spec, value):
    """A value out of the change trail, formatted where it still can be.

    A change recorded before the variable changed type holds something the spec
    can no longer read. It is history and cannot be corrected, so it is handed
    over as it was stored rather than costing the whole listing.
    """
    try:
        return _variable_value(spec, value)
    except (ArithmeticError, TypeError, ValueError):
        return value


def variable_entries() -> List[dict]:
    """Every variable this deployment knows, with what it is worth and who last changed it.

    The whole list, in key order: a variable nobody has overridden is shown at its
    default rather than left out, because a console that only listed overrides
    would not say what could be set. ``value`` is what everything reads right now
    — the row's, or the default when there is none — and ``overridden`` says which
    of the two it is.

    ``last_change`` is the most recent entry in the variable's trail, with the
    reason its author gave; ``None`` for a variable nobody has ever changed. It is
    read for the whole listing in two queries rather than one per variable.
    """
    rows = {
        row.key: row
        for row in PlatformVariable.objects.select_related("updated_by").all()
    }
    changes = _latest_changes(rows.values())
    in_force = variables.all_variables()
    entries = []
    for key in sorted(variables.VARIABLES):
        spec = variables.VARIABLES[key]
        row = rows.get(key)
        entries.append(
            {
                "key": key,
                "kind": spec.kind,
                "description": spec.description,
                "default": _variable_value(spec, spec.default),
                "value": _variable_value(spec, in_force[key]),
                "overridden": row is not None,
                "updated_at": _moment(row.updated_at) if row is not None else None,
                "updated_by": user_summary(row.updated_by) if row is not None else None,
                "last_change": _change_entry(spec, changes.get(row.pk)) if row is not None else None,
            }
        )
    return entries


def _latest_changes(rows) -> dict:
    """``{variable id: its most recent change}``, in two queries however many variables."""
    ids = [row.pk for row in rows]
    if not ids:
        return {}
    newest = (
        PlatformVariableChange.objects.filter(variable_id__in=ids)
        .values("variable_id")
        .annotate(newest=Max("id"))
        .values_list("newest", flat=True)
    )
    return {
        change.variable_id: change
        for change in PlatformVariableChange.objects.filter(id__in=list(newest)).select_related(
            "changed_by"
        )
    }


def _change_entry(spec, change) -> Optional[dict]:
    if change is None:
        return None
    return {
        "old_value": _stored_value(spec, change.old_value),
        "new_value": _stored_value(spec, change.new_value),
        "reason": change.reason,
        "changed_at": _moment(change.changed_at),
        "changed_by": user_summary(change.changed_by),
    }


def change_variable(key: str, value, *, user, reason: str) -> dict:
    """Override ``key`` and return its entry, as the listing shows it.

    The change itself is ``platform_variables.set_variable``, which records who
    made it and why; this is what the console reads back afterwards. An unknown
    key or an unusable value raises out of that service.
    """
    variables.set_variable(key, value, user=user, reason=reason)
    return variable_entry(key)


def variable_entry(key: str) -> dict:
    """One variable's entry, by key. Raises ``UnknownPlatformVariable`` for a key nobody declared."""
    # Through the spec rather than the listing, so an unknown key is refused by
    # the service that owns that question rather than by a missing dictionary key.
    variables.get_variable(key)
    return next(entry for entry in variable_entries() if entry["key"] == key)


# ── What each meter costs ────────────────────────────────────────────


def meter_price_entries(meter: Optional[str] = None) -> List[dict]:
    """Every meter's price history, newest first, with the row in force marked.

    One entry per meter, in key order, each carrying every price ever entered for
    it. Prices are only ever added, so this is the whole record of what the
    deployment has charged for that meter and when it changed.

    Which row is in force is asked of ``pricing.price_for`` rather than worked out
    again here, so that what the console marks as current is what an invoice would
    be calculated from. ``in_force`` is ``None`` for a meter whose every price
    starts later than now, which is what a price entered with the wrong date looks
    like — and until one starts, metering it bills nothing at all.
    """
    prices = MeterPrice.objects.all()
    if meter:
        prices = prices.filter(meter=meter)
    prices = prices.order_by("meter", "-effective_from", "-id")

    grouped = {}
    for price in prices:
        grouped.setdefault(price.meter, []).append(price)

    default_margin = variables.get_variable("usage_margin")
    return [
        _meter_entry(name, rows, default_margin) for name, rows in sorted(grouped.items())
    ]


def _meter_entry(name: str, rows, default_margin: Decimal) -> dict:
    current = _in_force(name)
    return {
        "meter": name,
        "in_force": current.pk if current is not None else None,
        "prices": [
            _price_entry(price, default_margin, current) for price in rows
        ],
    }


def _in_force(meter: str) -> Optional[MeterPrice]:
    try:
        return pricing.price_for(meter)
    except pricing.MeterNotPriced:
        return None


def _price_entry(price: MeterPrice, default_margin: Decimal, current) -> dict:
    """One price row: what it costs, what that comes to, and whether it is the live one.

    ``margin`` is what the row itself names and is ``None`` for one that follows
    the deployment, which is not the same as one that names the same share by
    hand: the first moves when ``usage_margin`` moves and the second does not.
    ``points_per_unit`` is what one call or token is billed at, worked out by the
    pricing service so that it reads as the bill will.
    """
    return {
        "id": price.pk,
        "vendor_cost": _number(price.vendor_cost),
        "unit_size": price.unit_size,
        "margin": _number(price.margin),
        "effective_margin": _number(
            price.margin if price.margin is not None else Decimal(default_margin)
        ),
        "uses_default_margin": price.margin is None,
        "points_per_unit": _number(pricing.points_for(price.meter, 1, price=price)),
        "effective_from": _moment(price.effective_from),
        "created_at": _moment(price.created_at),
        "in_force": current is not None and current.pk == price.pk,
    }


def add_meter_price(meter: str, **columns) -> dict:
    """Add a price for ``meter`` and return that meter's entry, the new row included.

    The whole meter rather than only the row written, because the answer an
    operator wants is what the deployment will bill at now — a price dated behind
    one that already exists changes nothing today, and the entry says so.
    """
    price = pricing.add_price(meter, **columns)
    return _meter_entry(
        price.meter,
        list(
            MeterPrice.objects.filter(meter=price.meter).order_by("-effective_from", "-id")
        ),
        variables.get_variable("usage_margin"),
    )


# ── Exchange rates ───────────────────────────────────────────────────


def exchange_rate_entries(
    *, base: Optional[str] = None, currency: Optional[str] = None, limit: int = RATES_DEFAULT_LIMIT
) -> List[dict]:
    """The rates most recently stored, newest day first and bounded.

    ``base`` and ``currency`` narrow it to one side of a pair. ``source`` says
    whether the row was read from the reference feed or entered by hand, which is
    what a bill calculated from it has to be explainable by.
    """
    from bfg.finance.models import ExchangeRate

    rates = ExchangeRate.objects.select_related("from_currency", "to_currency", "entered_by")
    if base:
        rates = rates.filter(from_currency__code=base.strip().upper())
    if currency:
        rates = rates.filter(to_currency__code=currency.strip().upper())
    # By id as well, so rates stored for the same day come back in a fixed order
    # rather than whichever one the database reaches first.
    rates = rates.order_by("-effective_date", "-id")[: max(1, min(limit, RATES_MAX_LIMIT))]
    return [_rate_entry(rate) for rate in rates]


def _rate_entry(rate) -> dict:
    return {
        "id": rate.pk,
        "from": rate.from_currency.code,
        "to": rate.to_currency.code,
        "rate": _number(rate.rate),
        "effective_date": rate.effective_date.isoformat(),
        "source": rate.source,
        "entered_by": user_summary(rate.entered_by),
    }


def set_exchange_rate(from_code: str, to_code: str, rate, *, on=None, user=None) -> dict:
    """Store a rate by hand and return its entry. See ``exchange_rates.set_rate``."""
    return _rate_entry(exchange_rates.set_rate(from_code, to_code, rate, on=on, user=user))


# ── One workspace's monthly usage cap ────────────────────────────────


def usage_cap_entry(workspace) -> dict:
    """What ``workspace`` may spend in a month, and where that number comes from.

    ``cap_points`` is the workspace's own, and ``None`` for one that has none:
    that is not a cap of zero, which would stop it metering anything at all.
    ``effective_cap_points`` is what is actually enforced — the workspace's own,
    or the deployment's ``monthly_usage_cap_points`` — and ``source`` says which
    of the two it came from, so a console can show a cap being inherited rather
    than making the reader compare two numbers.

    All three are written to the same scale, the column's own, so that a cap
    inherited from the deployment reads as one set on the workspace.
    """
    profile = getattr(workspace, "platform_profile", None)
    own = getattr(profile, "monthly_usage_cap_points", None) if profile is not None else None
    return {
        "workspace": workspace.pk,
        "cap_points": _cap(own),
        "default_cap_points": _cap(variables.get_variable("monthly_usage_cap_points")),
        "effective_cap_points": _cap(usage.monthly_cap(workspace)),
        "source": "workspace" if own is not None else "platform",
    }


def _cap(value) -> Optional[str]:
    """A number of points as the cap column holds it, or ``None`` left as it is.

    To a fixed scale because the deployment's default does not come from that
    column and so has no scale of its own — and because what it is worth depends
    on whether it was read through the variable cache, which writes it as a JSON
    number and reads it back with a trailing zero.
    """
    if value is None:
        return None
    value = Decimal(value)
    try:
        value = value.quantize(_CAP_SCALE)
    except ArithmeticError:
        # Larger than the scale can express, which the column would refuse
        # anyway; reported as it stands rather than not at all.
        pass
    return _number(value)


def set_usage_cap(workspace, points) -> dict:
    """Give ``workspace`` a cap of its own, or ``None`` to put it back on the default."""
    usage.set_monthly_cap(workspace, points)
    # Read back through the profile this just wrote, rather than through whatever
    # the workspace was loaded with, so the entry is what the column now holds.
    workspace.refresh_from_db()
    return usage_cap_entry(workspace)


# ── Entitlements given rather than sold ──────────────────────────────


def grant_entitlement(workspace, key: str, *, months: Optional[int], reason: str, user=None) -> dict:
    """Give ``workspace`` an entitlement to ``key`` and say what became of the extension.

    ``months`` is how long it runs, and ``None`` grants one that does not expire.
    ``key`` is an add-on's extension key, or the empty string for the base plan.

    A workspace that already holds a live entitlement to the key is refused with
    ``AlreadyEntitled`` rather than given a second row. Two live rows for one key
    are not wrong — a renewal writes a new row while the old one runs — but they
    are two things to renew and two to explain, and a second grant is almost
    always somebody granting the same thing twice. Whoever really means to extend
    an entitlement past its period is served by granting again once it has ended.

    The workspace row is held for the check and the write together, so two
    administrators granting at the same moment cannot both find it unentitled.

    **The extension is not switched on.** What a workspace is entitled to and what
    it has switched on are deliberately separate — see ``WorkspaceEntitlement`` —
    and switching one on changes what the workspace's own staff and customers see,
    runs the extension's activation hooks and can be refused by its prerequisites.
    That is the workspace's decision, not a side effect of the platform granting
    it. The one exception is an extension **the platform itself paused** when an
    entitlement ran out: the workspace had it on, pausing kept its data and
    configuration precisely so that being entitled again would restore it, so this
    resumes it. The ``extension`` in the answer says which of those happened.
    """
    from bfg.common.models import Workspace

    with transaction.atomic():
        # Nothing here holds the entitlement rows themselves, because the row
        # being guarded against is one that does not exist yet; the workspace is
        # the one thing two concurrent grants have in common.
        Workspace.objects.select_for_update().filter(pk=workspace.pk).first()
        live = _live_entitlement(workspace, key)
        if live is not None:
            raise AlreadyEntitled(
                f"This workspace is already entitled to {key or 'the base plan'}.",
                details={"key": key, "entitlement": _entitlement_entry(live)},
            )
        row = entitlements.grant(workspace, key, months=months, reason=reason)

    return {
        "workspace": workspace.pk,
        "entitlement": _entitlement_entry(row),
        "extension": _resume_if_paused(workspace, key, user=user),
    }


def _live_entitlement(workspace, key: str):
    """The row already entitling ``workspace`` to ``key``, if one does.

    Asked with ``entitlements.live_filter`` rather than a rule of its own, so that
    what counts as entitled here is what counts everywhere else.
    """
    return (
        WorkspaceEntitlement.all_objects.filter(workspace=workspace, key=key)
        .filter(entitlements.live_filter())
        .order_by("-starts_at", "-id")
        .first()
    )


def _entitlement_entry(row) -> dict:
    return {
        "id": row.pk,
        "key": row.key,
        "status": row.status,
        "source": row.source,
        "starts_at": _moment(row.starts_at),
        "current_period_end": _moment(row.current_period_end),
        "reason": row.reason,
    }


def _resume_if_paused(workspace, key: str, *, user=None) -> Optional[dict]:
    """Switch ``key`` back on for ``workspace`` if the entitlement sweep paused it.

    ``None`` for the base plan, which is not an extension, and for a key the
    workspace has no record of. Otherwise the extension's state after this, with
    ``resumed`` saying whether the grant switched it back on.

    Only a record the platform paused for want of an entitlement is touched, never
    one the workspace switched off itself. Nothing raised here is allowed to reach
    the caller: the entitlement is already written and committed, and reporting a
    grant that happened as a failure would have somebody grant it a second time.

    The workspace is bound while the extension's own code runs — its activation
    hook, the prerequisites it declares — since a platform request binds none and
    that code reads tenant-scoped models through ``objects``.
    """
    from bfg.common.extensions import services as extension_services
    from bfg.common.middleware import bound_workspace
    from bfg.common.models import WorkspaceExtension

    if key == WorkspaceEntitlement.KEY_BASE_PLAN:
        return None
    record = WorkspaceExtension.all_objects.filter(workspace=workspace, key=key).first()
    if record is None:
        return None

    entry = {"key": key, "status": record.status, "resumed": False, "refusal": None}
    if not (
        record.status == WorkspaceExtension.STATUS_PAUSED
        and record.status_reason == entitlements.PAUSED_REASON
    ):
        return entry

    try:
        with bound_workspace(workspace):
            resumed = extension_services.activate(workspace, key, user=user)
    except extension_services.ExtensionError as refusal:
        # A prerequisite that has since stopped being met, or a required
        # extension switched off in the meantime. The grant stands; somebody has
        # to switch this on once the reason is dealt with.
        logger.info("Granting %s to workspace %s did not resume it: %s", key, workspace.pk, refusal.code)
        entry["refusal"] = {"code": refusal.code, "detail": refusal.message}
        return entry
    except Exception:
        logger.exception("Could not resume %s for workspace %s after granting it", key, workspace.pk)
        entry["refusal"] = {"code": "resume_failed", "detail": "The extension could not be switched back on."}
        return entry

    entry["status"] = resumed.status
    entry["resumed"] = True
    return entry


def extension_key_exists(key: str) -> bool:
    """Whether ``key`` names an extension a workspace could switch on.

    The base plan, whose key is empty, is not an extension and is always granted
    by that name. Anything else has to be a deployed workspace-scoped extension:
    an entitlement to a key no app declares is a typo that nothing would ever
    read, and it is cheaper to refuse it than to explain it later.
    """
    if key == WorkspaceEntitlement.KEY_BASE_PLAN:
        return True
    manifest = registry.get_manifest(key)
    return manifest is not None and manifest.is_activatable

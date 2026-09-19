# -*- coding: utf-8 -*-
"""Atomic, idempotent metering for Platform runtime consumers."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from bfg.platform.services.configuration_service import platform_variable_decimal


class MeteringError(Exception):
    """Base error for a rejected metered operation."""


class MeteringIdempotencyKeyRequired(MeteringError):
    """A priced call needs a stable caller key before it can be charged."""


class WorkspaceUsageCapExceeded(MeteringError):
    """The next priced action would exceed the workspace's monthly allowance."""


@dataclass(frozen=True)
class MeterUsageResult:
    """The durable outcome of one meter check/record operation."""

    metered: bool
    record_id: int | None = None
    points: Decimal = Decimal("0.0000")
    usage_after: Decimal = Decimal("0.0000")
    cap_points: Decimal | None = None


def _period_start(moment) -> date:
    return date(moment.year, moment.month, 1)


def _current_price(meter: str, moment):
    MeterPrice = apps.get_model("platform", "PlatformMeterPrice")
    return MeterPrice.objects.filter(meter=meter).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=moment)
    ).order_by("-effective_from", "-created_at", "-id").first()


def _points_for(price, units: Decimal) -> Decimal:
    margin = price.margin
    if margin is None:
        margin = platform_variable_decimal("default_meter_margin")
    return (
        (price.vendor_cost / Decimal(price.unit_size)) * (Decimal("1") + margin) * units
    ).quantize(Decimal("0.0001"))


def _positive_units(units) -> Decimal:
    try:
        value = Decimal(str(units))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Meter units must be a positive decimal.") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("Meter units must be a positive decimal.")
    return value.quantize(Decimal("0.0001"))


def record_meter_usage(workspace, meter: str, units, *, idempotency_key: str | None, at=None) -> MeterUsageResult:
    """Atomically charge one configured meter, respecting the workspace cap.

    An absent effective price leaves a consumer unmetered for backward
    compatibility.  Once an operator configures a price, every caller must
    supply a stable idempotency key so retries cannot produce duplicate charges.
    """
    moment = at or timezone.now()
    price = _current_price(meter, moment)
    if not price:
        return MeterUsageResult(metered=False)

    key = str(idempotency_key or "").strip()
    if not 8 <= len(key) <= 128:
        raise MeteringIdempotencyKeyRequired
    quantity = _positive_units(units)
    points = _points_for(price, quantity)
    period_start = _period_start(moment)

    Workspace = apps.get_model("common", "Workspace")
    Usage = apps.get_model("platform", "WorkspaceMeterUsage")
    UsageCap = apps.get_model("platform", "WorkspaceUsageCap")
    with transaction.atomic():
        # This lock serializes both usage aggregation and first-record creation
        # for a workspace, making the cap safe across concurrent requests.
        locked_workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
        existing = Usage.objects.filter(
            workspace=locked_workspace, meter=meter, idempotency_key=key,
        ).first()
        if existing:
            used = Usage.objects.filter(
                workspace=locked_workspace, period_start=period_start,
            ).aggregate(total=Sum("points"))["total"] or Decimal("0.0000")
            own_cap = UsageCap.objects.filter(workspace=locked_workspace).values_list("cap_points", flat=True).first()
            return MeterUsageResult(
                metered=True,
                record_id=existing.id,
                points=existing.points,
                usage_after=used,
                cap_points=own_cap if own_cap is not None else platform_variable_decimal("default_usage_cap_points"),
            )

        own_cap = UsageCap.objects.filter(workspace=locked_workspace).values_list("cap_points", flat=True).first()
        cap = own_cap if own_cap is not None else platform_variable_decimal("default_usage_cap_points")
        used = Usage.objects.filter(
            workspace=locked_workspace, period_start=period_start,
        ).aggregate(total=Sum("points"))["total"] or Decimal("0.0000")
        if used + points > cap:
            raise WorkspaceUsageCapExceeded

        record = Usage.objects.create(
            workspace=locked_workspace,
            meter=meter,
            idempotency_key=key,
            units=quantity,
            points=points,
            period_start=period_start,
            price=price,
        )
        return MeterUsageResult(
            metered=True,
            record_id=record.id,
            points=points,
            usage_after=used + points,
            cap_points=cap,
        )

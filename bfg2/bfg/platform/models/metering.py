# -*- coding: utf-8 -*-
"""
What a metered call costs, and how much of it a workspace has made.

A *meter* is a named thing worth counting — one lookup against a paid API, one
token sent to a model — declared by the extension that spends it (``meters`` on
its manifest). A *point* is the billing unit: one point is one US dollar, which
keeps a bill readable when the vendor costs behind it are fractions of a cent.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bfg.common.managers import TenantScopedModel


class MeterPrice(models.Model):
    """What one meter costs from a given moment on.

    Prices are never edited in place: a vendor's new rate is a new row with a later
    ``effective_from``, so a bill that has already been calculated can still be
    explained. ``unit_size`` is how many calls or tokens ``vendor_cost`` buys — a
    vendor quoting "$5 per 1,000 requests" is ``vendor_cost=5``, ``unit_size=1000``.

    ``margin`` is the share added on top of the vendor cost, as a fraction: 0.30
    charges 1.30 times what the call costs. Left empty, the deployment's
    ``usage_margin`` variable applies, so a margin change moves every price that
    did not opt out of it.
    """

    meter = models.CharField(_("Meter"), max_length=100)
    vendor_cost = models.DecimalField(
        _("Vendor Cost (USD)"),
        max_digits=12,
        decimal_places=6,
        help_text=_("What the vendor charges for one unit_size of this meter."),
    )
    unit_size = models.PositiveIntegerField(
        _("Unit Size"),
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_("How many calls or tokens the vendor cost buys."),
    )
    margin = models.DecimalField(
        _("Margin"),
        max_digits=6,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("Share added on top of the vendor cost; empty uses the platform default."),
    )
    effective_from = models.DateTimeField(_("Effective From"), default=timezone.now)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Meter Price")
        verbose_name_plural = _("Meter Prices")
        ordering = ["meter", "-effective_from"]
        indexes = [
            models.Index(fields=["meter", "-effective_from"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_size__gt=0),
                name="platform_meter_price_unit_size_positive",
            ),
        ]

    def __str__(self):
        return f"{self.meter} @ {self.effective_from:%Y-%m-%d}"

    def points_per_unit(self, default_margin: Decimal) -> Decimal:
        """Points one call or token costs, margin included.

        ``default_margin`` is what applies when the row names no margin of its own;
        the caller passes it because reading the platform variable is a query the
        model should not be making.
        """
        margin = self.margin if self.margin is not None else Decimal(default_margin)
        return (Decimal(self.vendor_cost) / Decimal(self.unit_size)) * (Decimal(1) + margin)


class UsageRecord(TenantScopedModel):
    """How much of one meter a workspace used on one UTC day, and what that came to.

    Rolled up per day rather than per call: a bill is read by the day, and one row
    per API call would be the largest table in the deployment for numbers nobody
    reads at that resolution. ``price`` records which version of the price the
    points were calculated with, so a price that changes mid-day splits the day
    into one row per version and every row can still be explained.

    Workspace scoping is deliberately bypassed by everything that writes or reads
    these rows: they are written from Celery tasks and read by platform billing,
    neither of which has a workspace bound to the thread, where
    ``UsageRecord.objects`` would be empty. The services therefore go through
    ``all_objects`` and always filter by workspace themselves; ``objects`` stays
    the fail-closed default for anything that touches usage inside a request.
    """

    workspace = models.ForeignKey(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="usage_records",
    )
    meter = models.CharField(_("Meter"), max_length=100)
    day = models.DateField(_("Day (UTC)"))
    quantity = models.DecimalField(_("Quantity"), max_digits=18, decimal_places=4, default=Decimal("0"))
    points = models.DecimalField(_("Points"), max_digits=16, decimal_places=8, default=Decimal("0"))
    price = models.ForeignKey(
        MeterPrice,
        verbose_name=_("Price"),
        on_delete=models.PROTECT,
        related_name="usage_records",
    )
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Usage Record")
        verbose_name_plural = _("Usage Records")
        ordering = ["-day", "meter"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "meter", "day", "price"],
                name="platform_usage_record_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "day"]),
            models.Index(fields=["meter", "day"]),
        ]
        base_manager_name = "all_objects"

    def __str__(self):
        return f"{self.meter} × {self.quantity} = {self.points} pt (workspace {self.workspace_id}, {self.day})"

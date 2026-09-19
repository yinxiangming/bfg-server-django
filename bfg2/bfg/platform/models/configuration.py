# -*- coding: utf-8 -*-
"""Durable configuration owned by the Platform control plane."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PlatformVariableOverride(models.Model):
    """One current override of a named, code-declared Platform variable."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    reason = models.CharField(max_length=500)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_variable_overrides",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]


class PlatformVariableChange(models.Model):
    """Append-only explanation for each effective Platform-variable change."""

    key = models.CharField(max_length=100, db_index=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=500)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_variable_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-changed_at", "-id"]
        indexes = [models.Index(fields=["key", "-changed_at"], name="plat_variable_change_idx")]


class PlatformMeterPrice(models.Model):
    """An immutable price for a metered Platform capability from a point in time."""

    meter = models.CharField(max_length=100, db_index=True)
    vendor_cost = models.DecimalField(max_digits=20, decimal_places=8)
    unit_size = models.PositiveIntegerField()
    margin = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    effective_from = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_meter_prices",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["meter", "-effective_from", "-created_at", "-id"]
        indexes = [models.Index(fields=["meter", "effective_from"], name="plat_meter_effective_idx")]


class PlatformMeterPriceRequest(models.Model):
    """One superuser's idempotent request to append a meter price.

    Price history stays immutable and is allowed to contain equal rates entered at
    different times. This separate record instead binds a client retry key to one
    exact normalized request and the price it produced, without changing history.
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_meter_price_requests",
    )
    idempotency_key = models.CharField(max_length=128)
    payload_hash = models.CharField(max_length=64)
    price = models.OneToOneField(
        "platform.PlatformMeterPrice",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="idempotency_request",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "idempotency_key"],
                name="platform_meter_price_request_key",
            ),
        ]


class PlatformActionRequest(models.Model):
    """One durable retry boundary for a Platform action with external effects.

    The stored response is deliberately a small, public-safe payload. It lets a
    network retry return the original result without repeating email delivery or
    other side effects, while keeping credentials and exception details out of
    the database record and browser response.
    """

    RESULT_PENDING = "pending"
    RESULT_SUCCEEDED = "succeeded"
    RESULT_FAILED = "failed"
    RESULT_CHOICES = [
        (RESULT_PENDING, _("Pending")),
        (RESULT_SUCCEEDED, _("Succeeded")),
        (RESULT_FAILED, _("Failed")),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_action_requests",
    )
    idempotency_key = models.CharField(max_length=128)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=255)
    payload_hash = models.CharField(max_length=64)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, default=RESULT_PENDING)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "idempotency_key"],
                name="platform_action_request_key",
            ),
        ]


class WorkspaceUsageCap(models.Model):
    """Optional monthly metered-usage cap selected by a Platform administrator."""

    workspace = models.OneToOneField(
        "common.Workspace",
        on_delete=models.CASCADE,
        related_name="platform_usage_cap",
    )
    cap_points = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workspace_usage_cap_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)


class WorkspaceMeterUsage(models.Model):
    """One idempotent, price-snapshotted metered action by a workspace."""

    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.CASCADE,
        related_name="platform_meter_usage",
    )
    meter = models.CharField(max_length=100)
    # The caller keeps the same key when retrying one user action.  It is scoped
    # to the meter because a caller can independently invoke more than one meter.
    idempotency_key = models.CharField(max_length=128)
    units = models.DecimalField(max_digits=20, decimal_places=4)
    points = models.DecimalField(max_digits=20, decimal_places=4)
    period_start = models.DateField(db_index=True)
    price = models.ForeignKey(
        "platform.PlatformMeterPrice",
        null=True,
        on_delete=models.PROTECT,
        related_name="usage_records",
    )
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "meter", "idempotency_key"],
                name="platform_meter_usage_idempotency",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "meter", "period_start"],
                name="platform_meter_usage_period",
            ),
        ]


class WorkspaceEntitlement(models.Model):
    """A Platform-granted entitlement; it does not itself enable an extension."""

    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, _("Active")),
        (STATUS_EXPIRED, _("Expired")),
        (STATUS_REVOKED, _("Revoked")),
    ]

    SOURCE_PLATFORM_GRANT = "platform_grant"
    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.CASCADE,
        related_name="platform_entitlements",
    )
    key = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    source = models.CharField(max_length=40, default=SOURCE_PLATFORM_GRANT)
    starts_at = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workspace_entitlement_grants",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace", "key", "status"], name="plat_entitlement_lookup_idx")]

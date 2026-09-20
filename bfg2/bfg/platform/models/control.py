# -*- coding: utf-8 -*-
"""Durable evidence and retry boundaries for Platform control-plane writes."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatformAuditEvent(models.Model):
    """An append-only, redacted record of a sensitive control-plane action."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=255)
    reason = models.CharField(max_length=500)
    result = models.CharField(max_length=32, default="succeeded")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_control_audit_events",
    )
    request_id = models.UUIDField(null=True, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id", "-created_at"], name="plat_ctrl_audit_target_idx"),
            models.Index(fields=["action", "-created_at"], name="plat_ctrl_audit_action_idx"),
            models.Index(fields=["actor", "-created_at"], name="plat_ctrl_audit_actor_idx"),
        ]


class PlatformControlActionRequest(models.Model):
    """A durable retry boundary for one confirmed control-plane request."""

    RESULT_PENDING = "pending"
    RESULT_SUCCEEDED = "succeeded"
    RESULT_FAILED = "failed"
    RESULT_CHOICES = [
        (RESULT_PENDING, "Pending"),
        (RESULT_SUCCEEDED, "Succeeded"),
        (RESULT_FAILED, "Failed"),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_control_action_requests",
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
                name="platform_control_request_key",
            ),
        ]


class ClusterHealthObservation(models.Model):
    """One redaction-safe result from a server-side Cluster health probe."""

    OUTCOME_CHECKED = "checked"
    OUTCOME_CONFIGURATION_UNAVAILABLE = "configuration_unavailable"
    OUTCOME_CONFIGURATION_CHANGED = "configuration_changed"
    OUTCOME_CHOICES = [
        (OUTCOME_CHECKED, "Checked"),
        (OUTCOME_CONFIGURATION_UNAVAILABLE, "Configuration unavailable"),
        (OUTCOME_CONFIGURATION_CHANGED, "Configuration changed"),
    ]

    cluster = models.ForeignKey(
        "platform.Cluster",
        on_delete=models.PROTECT,
        related_name="health_observations",
    )
    health_status = models.CharField(max_length=20)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=32, choices=OUTCOME_CHOICES, default=OUTCOME_CHECKED)
    observed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cluster_health_observations",
    )
    observed_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-observed_at", "-id"]
        indexes = [
            models.Index(fields=["cluster", "-observed_at"], name="plat_cluster_health_obs_idx"),
        ]


class WorkspacePlacementRequest(models.Model):
    """A fenced, reversible capacity reservation for a future placement.

    A reservation is deliberately not a change to ``WorkspacePlatformProfile.cluster``.
    Applying one requires an authenticated data-plane adapter to prove the tenant data
    was copied and cut over. Keeping that boundary explicit prevents the control plane
    from claiming that a live Workspace has moved when only its routing metadata changed.
    """

    STATUS_RESERVED = "reserved"
    STATUS_ROLLED_BACK = "rolled_back"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_RESERVED, "Capacity reserved"),
        (STATUS_ROLLED_BACK, "Rolled back"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.PROTECT,
        related_name="placement_requests",
    )
    source_cluster = models.ForeignKey(
        "platform.Cluster",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="placement_requests_from",
    )
    target_cluster = models.ForeignKey(
        "platform.Cluster",
        on_delete=models.PROTECT,
        related_name="placement_requests_to",
    )
    profile_fence = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RESERVED)
    reservation_expires_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workspace_placement_requests",
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["target_cluster", "status", "reservation_expires_at"], name="plat_place_target_idx"),
            models.Index(fields=["workspace", "status", "-created_at"], name="plat_place_workspace_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(status="reserved"),
                name="plat_place_one_active_per_workspace",
            ),
        ]


class WorkspacePlacementEvent(models.Model):
    """Ordered, redaction-safe progress evidence for one placement request."""

    request = models.ForeignKey(
        WorkspacePlacementRequest,
        on_delete=models.CASCADE,
        related_name="events",
    )
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=40)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["sequence", "id"]
        constraints = [
            models.UniqueConstraint(fields=["request", "sequence"], name="plat_place_event_sequence"),
        ]

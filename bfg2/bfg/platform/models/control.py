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

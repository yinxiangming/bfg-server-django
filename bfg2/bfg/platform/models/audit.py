# -*- coding: utf-8 -*-
"""Append-only records for Platform control-plane actions."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatformAuditEvent(models.Model):
    """A durable record of a sensitive Platform action.

    The model deliberately identifies a target by a stable type/id pair instead of a
    foreign key. A later workspace deletion must not erase the evidence that an
    administrator scheduled it, and cluster changes have no workspace foreign key.
    Application code creates these records only; there is no update or delete API.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=255)
    reason = models.CharField(max_length=500)
    # The final server-side outcome, deliberately separate from arbitrary
    # exception detail that must remain in secured logs.
    result = models.CharField(max_length=32, default="succeeded")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_audit_events",
    )
    request_id = models.UUIDField(null=True, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_type", "target_id", "-created_at"], name="plat_audit_target_time_idx"),
            models.Index(fields=["action", "-created_at"], name="plat_audit_action_time_idx"),
            models.Index(fields=["actor", "-created_at"], name="plat_audit_actor_time_idx"),
        ]

    def __str__(self):
        return f"{self.action} {self.target_type}:{self.target_id}"

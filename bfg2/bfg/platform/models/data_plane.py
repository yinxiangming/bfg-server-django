"""Durable metadata for workspace data-plane snapshots."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class WorkspaceDataSnapshot(models.Model):
    """A content-addressed workspace data archive and its verification state.

    The archive itself is kept in the configured data-plane storage.  This row is
    deliberately separate from ``WorkspaceOperation`` so an operation can be
    retried without losing the identity of an already exported artifact.
    """

    KIND_ARCHIVE = "archive"
    KIND_TRANSFER = "transfer"
    KIND_RESTORE = "restore"
    KIND_CHOICES = (
        (KIND_ARCHIVE, "Archive"),
        (KIND_TRANSFER, "Transfer"),
        (KIND_RESTORE, "Restore"),
    )

    STATUS_PENDING = "pending"
    STATUS_EXPORTING = "exporting"
    STATUS_READY = "ready"
    STATUS_VERIFYING = "verifying"
    STATUS_VERIFIED = "verified"
    STATUS_RESTORING = "restoring"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_EXPORTING, "Exporting"),
        (STATUS_READY, "Ready"),
        (STATUS_VERIFYING, "Verifying"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_RESTORING, "Restoring"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.PROTECT,
        related_name="data_snapshots",
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_ARCHIVE)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    artifact_uri = models.CharField(max_length=500, blank=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    manifest_sha256 = models.CharField(max_length=64, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    row_count = models.PositiveBigIntegerField(default=0)
    media_count = models.PositiveBigIntegerField(default=0)
    media_bytes = models.PositiveBigIntegerField(default=0)
    source_cluster_id = models.CharField(max_length=32, blank=True)
    target_cluster_id = models.CharField(max_length=32, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_data_snapshots",
    )
    failure_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="plat_snapshot_ws_time_idx"),
            models.Index(fields=["status", "-created_at"], name="plat_snapshot_status_idx"),
        ]

    def __str__(self):
        return f"{self.workspace_id}:{self.id} [{self.status}]"

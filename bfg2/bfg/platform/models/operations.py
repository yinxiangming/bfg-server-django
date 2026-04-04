# -*- coding: utf-8 -*-
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings


class WorkspaceOperation(models.Model):
    """
    Tracks asynchronous operations performed on a Workspace
    (provisioning, suspension, migration, deletion, etc.).
    """
    OPERATIONS = [
        ("create", _("Create")),
        ("suspend", _("Suspend")),
        ("resume", _("Resume")),
        ("migrate", _("Migrate")),
        ("delete", _("Delete")),
    ]

    STATUSES = [
        ("pending", _("Pending")),
        ("running", _("Running")),
        ("completed", _("Completed")),
        ("failed", _("Failed")),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="operations",
    )
    operation = models.CharField(_("Operation"), max_length=50, choices=OPERATIONS)
    status = models.CharField(_("Status"), max_length=20, choices=STATUSES, default="pending")

    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Initiated By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_operations",
    )

    # Payload / result
    details = models.JSONField(_("Details"), default=dict, blank=True)
    error_message = models.TextField(_("Error Message"), blank=True)

    # Timestamps
    started_at = models.DateTimeField(_("Started At"), default=timezone.now)
    completed_at = models.DateTimeField(_("Completed At"), null=True, blank=True)

    class Meta:
        verbose_name = _("Workspace Operation")
        verbose_name_plural = _("Workspace Operations")
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["workspace", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.get_operation_display()} on {self.workspace} [{self.status}]"

    def mark_running(self):
        """Mark operation as running."""
        self.status = "running"
        self.save(update_fields=["status"])

    def mark_completed(self, details=None):
        """Mark operation as completed."""
        self.status = "completed"
        self.completed_at = timezone.now()
        if details:
            self.details = {**self.details, **details}
        self.save(update_fields=["status", "completed_at", "details"])

    def mark_failed(self, error_message=""):
        """Mark operation as failed with an error message."""
        self.status = "failed"
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save(update_fields=["status", "completed_at", "error_message"])

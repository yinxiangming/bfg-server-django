# -*- coding: utf-8 -*-
import hashlib
import secrets
import uuid as uuid_lib

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(48)


class Invitation(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REVOKED = "revoked"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REVOKED, "Revoked"),
        (STATUS_EXPIRED, "Expired"),
    ]

    uuid = models.UUIDField(default=uuid_lib.uuid4, unique=True, editable=False)
    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name=_("Workspace"),
    )
    email = models.EmailField(_("Email"), db_index=True)
    role = models.ForeignKey(
        "common.StaffRole",
        on_delete=models.PROTECT,
        related_name="invitations",
        verbose_name=_("Role"),
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
        verbose_name=_("Invited By"),
    )

    token_hash = models.CharField(max_length=128, unique=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    expires_at = models.DateTimeField(_("Expires At"))
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invitations",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    message = models.TextField(_("Message"), blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Invitation")
        verbose_name_plural = _("Invitations")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "email"],
                condition=models.Q(status="pending"),
                name="uniq_pending_invite_per_workspace_email",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["email", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.workspace_id} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def effective_status(self) -> str:
        """Return current status, lazily flipping pending → expired when past expiry."""
        if self.status == self.STATUS_PENDING and self.is_expired:
            return self.STATUS_EXPIRED
        return self.status

    def mark_expired(self, save: bool = True) -> None:
        if self.status == self.STATUS_PENDING:
            self.status = self.STATUS_EXPIRED
            if save:
                self.save(update_fields=["status", "updated_at"])

    def mark_revoked(self, save: bool = True) -> None:
        self.status = self.STATUS_REVOKED
        self.revoked_at = timezone.now()
        if save:
            self.save(update_fields=["status", "revoked_at", "updated_at"])

    def mark_accepted(self, user, save: bool = True) -> None:
        self.status = self.STATUS_ACCEPTED
        self.accepted_at = timezone.now()
        self.accepted_by = user
        if save:
            self.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])

# -*- coding: utf-8 -*-
"""
API Key model for workspace-level programmatic access.

Each workspace can create multiple API keys. A key consists of:
- `prefix` (public, 8 chars) — used to look up the key quickly.
- `secret` — returned in plain text **only once** at creation time;
  the database stores a SHA-256 hash (`secret_hash`).
"""

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Public prefix length (used for lookup / display)
API_KEY_PREFIX_LENGTH = 8
# Secret raw length in bytes; hex-encoded = 2× characters
API_KEY_SECRET_BYTES = 32


def generate_api_key_prefix() -> str:
    """Generate a random URL-safe prefix for an API key."""
    return secrets.token_hex(API_KEY_PREFIX_LENGTH // 2)  # 8 hex chars


def generate_api_key_secret() -> str:
    """Generate a random secret for an API key."""
    return secrets.token_hex(API_KEY_SECRET_BYTES)  # 64 hex chars


def hash_secret(secret: str) -> str:
    """Return the SHA-256 hex digest of the raw secret."""
    return hashlib.sha256(secret.encode()).hexdigest()


class APIKey(models.Model):
    """
    Workspace-scoped API key.

    The key is identified publicly by its *prefix* (shown in lists / logs).
    The *secret* is hashed (SHA-256) before storage — the plain-text secret
    is returned **only** in the API response to the ``POST`` that creates the key.
    """

    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='api_keys',
        verbose_name=_("Workspace"),
    )

    name = models.CharField(
        _("Name"),
        max_length=255,
        help_text=_("Human-readable label for this key, e.g. 'Shopify sync'."),
    )

    # ── Key material ──────────────────────────────────────────────
    prefix = models.CharField(
        _("Key Prefix"),
        max_length=16,
        unique=True,
        db_index=True,
        editable=False,
        help_text=_("Public prefix used for lookup (displayed as the 'API Key')."),
    )

    secret_hash = models.CharField(
        _("Secret Hash"),
        max_length=64,
        editable=False,
        help_text=_("SHA-256 hash of the secret. The raw secret is never stored."),
    )

    # ── Metadata ──────────────────────────────────────────────────
    is_active = models.BooleanField(_("Active"), default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_api_keys',
        verbose_name=_("Created By"),
    )

    last_used_at = models.DateTimeField(
        _("Last Used At"),
        null=True,
        blank=True,
    )

    expires_at = models.DateTimeField(
        _("Expires At"),
        null=True,
        blank=True,
        help_text=_("Optional expiration date. Null means never expires."),
    )

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("API Key")
        verbose_name_plural = _("API Keys")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    # ── Helpers ────────────────────────────────────────────────────

    def verify_secret(self, raw_secret: str) -> bool:
        """Return ``True`` if *raw_secret* matches the stored hash."""
        return hash_secret(raw_secret) == self.secret_hash

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the key has passed its expiry date."""
        if self.expires_at is None:
            return False
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        """Return ``True`` if the key is active and not expired."""
        return self.is_active and not self.is_expired

    def record_usage(self):
        """Stamp *last_used_at* without triggering ``auto_now`` on *updated_at*."""
        APIKey.objects.filter(pk=self.pk).update(last_used_at=timezone.now())

    @classmethod
    def create_key(cls, workspace, name, created_by=None, expires_at=None):
        """
        Create a new API key and return ``(instance, raw_secret)``.

        The *raw_secret* is the only time the caller can see the plain-text
        secret — it is **not** persisted in the database.
        """
        prefix = generate_api_key_prefix()
        raw_secret = generate_api_key_secret()

        instance = cls.objects.create(
            workspace=workspace,
            name=name,
            prefix=prefix,
            secret_hash=hash_secret(raw_secret),
            created_by=created_by,
            expires_at=expires_at,
        )
        return instance, raw_secret

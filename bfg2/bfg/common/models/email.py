# -*- coding: utf-8 -*-
"""
EmailConfig model for per-workspace email sending (SMTP, Mailgun, etc.).
Backend types are taken from email_backends registry, not hardcoded.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


def _get_backend_type_choices():
    """Resolve choices from email_backends registry to avoid circular import at module load."""
    from bfg.common.email_backends import get_backend_type_choices
    return get_backend_type_choices()


class EmailConfig(models.Model):
    """
    Per-workspace email backend configuration.
    One config per workspace can be marked is_default for sending.
    backend_type choices come from registered backends in email_backends.
    """

    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='email_configs',
        verbose_name=_("Workspace")
    )
    name = models.CharField(_("Name"), max_length=255, help_text=_("Display name e.g. Production SMTP"))
    backend_type = models.CharField(
        _("Backend Type"),
        max_length=50,
        choices=_get_backend_type_choices,
        help_text=_("Determines config structure and sending method")
    )
    config = models.JSONField(_("Configuration"), default=dict, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)
    is_default = models.BooleanField(_("Default for sending"), default=False)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Email Config")
        verbose_name_plural = _("Email Configs")
        ordering = ['-is_default', 'name']
        indexes = [
            models.Index(fields=['workspace', 'is_default']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_backend_type_display()})"

    def save(self, *args, **kwargs):
        if self.is_default:
            EmailConfig.objects.filter(
                workspace=self.workspace
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

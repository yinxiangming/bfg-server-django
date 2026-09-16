# -*- coding: utf-8 -*-
"""
Deployment-wide numbers an operator can change without a release.

Margins, grace periods and default caps are policy, not code: a deployment adjusts
them as it learns what its costs are. Every known variable has a default in
``bfg.platform.services.platform_variables``, so a deployment that never writes a
row still behaves sensibly, and a row only exists once someone has overridden it.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PlatformVariable(models.Model):
    """One overridden platform variable.

    ``value`` holds a JSON number or boolean. Rates and point amounts are read back
    as ``Decimal`` through ``Decimal(str(value))``, which is exact for the short
    decimal values these hold; the service is the only thing that should read the
    column, so callers never see the JSON representation.
    """

    key = models.CharField(_("Key"), max_length=64, unique=True)
    value = models.JSONField(_("Value"))
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Updated By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Platform Variable")
        verbose_name_plural = _("Platform Variables")
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value}"


class PlatformVariableChange(models.Model):
    """Who changed a platform variable, when, from what and why.

    Variables decide what workspaces are charged, so a change has to be answerable
    for long after it was made. ``old_value`` records the value that was in force,
    which is the variable's default when nothing had overridden it yet, rather than
    the absence of a row.
    """

    variable = models.ForeignKey(
        PlatformVariable,
        verbose_name=_("Variable"),
        on_delete=models.CASCADE,
        related_name="changes",
    )
    old_value = models.JSONField(_("Old Value"), null=True, blank=True)
    new_value = models.JSONField(_("New Value"))
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Changed By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    changed_at = models.DateTimeField(_("Changed At"), default=timezone.now)
    reason = models.CharField(_("Reason"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("Platform Variable Change")
        verbose_name_plural = _("Platform Variable Changes")
        ordering = ["-changed_at", "-id"]
        indexes = [
            models.Index(fields=["variable", "-changed_at"]),
        ]

    def __str__(self):
        return f"{self.variable_id}: {self.old_value} → {self.new_value}"

# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class FeatureDefinition(models.Model):
    """
    Defines a platform feature that can be enabled/disabled per workspace.
    Features are gated by subscription plans.
    """
    CATEGORY_CHOICES = [
        ("shop", _("Shop")),
        ("marketing", _("Marketing")),
        ("ai", _("AI")),
        ("support", _("Support")),
        ("finance", _("Finance")),
        ("web", _("Web")),
        ("core", _("Core")),
    ]

    # Primary key is the feature key (e.g., "shop.advanced_analytics")
    key = models.CharField(_("Key"), max_length=64, primary_key=True)
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    category = models.CharField(_("Category"), max_length=50, choices=CATEGORY_CHOICES)

    # Default state
    default_enabled = models.BooleanField(_("Default Enabled"), default=False)

    # Minimum plan required to use this feature (null = available on all plans)
    min_plan = models.ForeignKey(
        "shop.SubscriptionPlan",
        verbose_name=_("Minimum Plan"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gated_features",
    )

    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Feature Definition")
        verbose_name_plural = _("Feature Definitions")
        ordering = ["category", "key"]

    def __str__(self):
        return f"{self.name} ({self.key})"

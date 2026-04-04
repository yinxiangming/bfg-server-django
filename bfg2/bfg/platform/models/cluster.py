# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class Cluster(models.Model):
    """
    Cluster model representing a deployment cluster that hosts Workspaces.
    Each cluster has its own infrastructure resources (DB, Redis, S3, etc.).
    """
    REGION_CHOICES = [
        ("us", _("United States")),
        ("eu", _("Europe")),
        ("apac", _("Asia Pacific")),
    ]

    HEALTH_STATUS_CHOICES = [
        ("unknown", _("Unknown")),
        ("healthy", _("Healthy")),
        ("degraded", _("Degraded")),
        ("down", _("Down")),
    ]

    # Primary key (e.g., "us-east-1", "eu-west-1")
    id = models.CharField(_("ID"), max_length=32, primary_key=True)
    name = models.CharField(_("Name"), max_length=255)
    region = models.CharField(_("Region"), max_length=20, choices=REGION_CHOICES)

    # Infrastructure
    api_base_url = models.URLField(_("API Base URL"))
    frontend_base_url = models.URLField(_("Frontend Base URL"), blank=True, default="")
    db_host = models.CharField(_("DB Host"), max_length=255)
    db_port = models.IntegerField(_("DB Port"), default=3306)
    redis_url = models.URLField(_("Redis URL"))
    s3_bucket = models.CharField(_("S3 Bucket"), max_length=255)

    # Capacity
    max_workspaces = models.IntegerField(_("Max Workspaces"), default=500)
    current_workspaces = models.IntegerField(_("Current Workspaces"), default=0)
    is_accepting_new = models.BooleanField(_("Accepting New Workspaces"), default=True)

    # Status
    is_active = models.BooleanField(_("Active"), default=True)
    last_health_check = models.DateTimeField(_("Last Health Check"), null=True, blank=True)
    health_status = models.CharField(
        _("Health Status"), max_length=20, choices=HEALTH_STATUS_CHOICES, default="unknown"
    )

    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Cluster")
        verbose_name_plural = _("Clusters")
        ordering = ["region", "name"]

    def __str__(self):
        return f"{self.name} ({self.region})"

    @property
    def capacity_percentage(self):
        """Return the percentage of capacity used."""
        if self.max_workspaces == 0:
            return 100
        return int((self.current_workspaces / self.max_workspaces) * 100)

    @property
    def has_capacity(self):
        """Return True if this cluster can accept more workspaces."""
        return self.is_active and self.is_accepting_new and self.current_workspaces < self.max_workspaces

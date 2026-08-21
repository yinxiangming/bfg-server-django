# -*- coding: utf-8 -*-
"""
Workspace domain resolver helpers and model.
"""

from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from bfg.common.cache_policy import cache_ttl


class WorkspaceDomain(models.Model):
    KIND_SYSTEM_DEFAULT = "system_default"
    KIND_CUSTOM = "custom"
    KIND_CHOICES = [
        (KIND_SYSTEM_DEFAULT, _("System default")),
        (KIND_CUSTOM, _("Custom")),
    ]

    VERIFICATION_PENDING = "pending"
    VERIFICATION_VERIFIED = "verified"
    VERIFICATION_FAILED = "failed"
    VERIFICATION_STATUS_CHOICES = [
        (VERIFICATION_PENDING, _("Pending")),
        (VERIFICATION_VERIFIED, _("Verified")),
        (VERIFICATION_FAILED, _("Failed")),
    ]

    SSL_NONE = "none"
    SSL_PENDING = "pending"
    SSL_ACTIVE = "active"
    SSL_FAILED = "failed"
    SSL_STATUS_CHOICES = [
        (SSL_NONE, _("None")),
        (SSL_PENDING, _("Pending")),
        (SSL_ACTIVE, _("Active")),
        (SSL_FAILED, _("Failed")),
    ]

    workspace = models.ForeignKey(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="domains",
    )
    hostname = models.CharField(_("Hostname"), max_length=255, unique=True)
    kind = models.CharField(_("Kind"), max_length=20, choices=KIND_CHOICES)
    verification_status = models.CharField(
        _("Verification Status"),
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default=VERIFICATION_PENDING,
    )
    ssl_status = models.CharField(
        _("SSL Status"),
        max_length=20,
        choices=SSL_STATUS_CHOICES,
        default=SSL_NONE,
    )
    is_primary = models.BooleanField(_("Is Primary"), default=False)
    last_dns_check_at = models.DateTimeField(_("Last DNS Check At"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Workspace Domain")
        verbose_name_plural = _("Workspace Domains")
        ordering = ["workspace_id", "kind", "hostname"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(kind="system_default"),
                name="unique_system_default_domain_per_workspace",
            ),
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(is_primary=True),
                name="unique_primary_domain_per_workspace",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "kind"]),
            models.Index(fields=["workspace", "is_primary"]),
            models.Index(fields=["workspace", "verification_status"]),
        ]

    def __str__(self):
        return self.hostname

    def clean(self):
        self.hostname = normalize_hostname(self.hostname)
        if self.kind == self.KIND_SYSTEM_DEFAULT and self.is_primary:
            raise ValidationError({"is_primary": _("system_default domain cannot be primary")})
        if self.is_primary and self.kind != self.KIND_CUSTOM:
            raise ValidationError({"is_primary": _("Only custom domains can be primary")})
        if self.is_primary and self.verification_status != self.VERIFICATION_VERIFIED:
            raise ValidationError({"verification_status": _("Primary domain must be verified")})

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            saved = super().save(*args, **kwargs)
            if self.kind == self.KIND_SYSTEM_DEFAULT:
                WorkspaceDomain.objects.filter(
                    workspace=self.workspace,
                    kind=self.KIND_SYSTEM_DEFAULT,
                ).exclude(pk=self.pk).delete()
            if self.is_primary:
                WorkspaceDomain.objects.filter(
                    workspace=self.workspace,
                    kind=self.KIND_CUSTOM,
                    is_primary=True,
                ).exclude(pk=self.pk).update(is_primary=False)
            return saved


def normalize_hostname(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = parsed.netloc or parsed.path or raw
    host = host.split("/")[0].split(":")[0].strip().lower()
    if host.startswith("www."):
        return host[4:]
    return host


def get_workspace_domain_cache_key(hostname: str) -> str:
    return f"workspace:domain:{normalize_hostname(hostname)}"


def get_workspace_frontend_base_url_cache_key(workspace_id: int) -> str:
    return f"workspace:frontend-base-url:{workspace_id}"


def resolve_workspace_public_frontend_base_url(workspace, override_domain=None) -> str:
    normalized_override = normalize_hostname(override_domain or "")
    if normalized_override:
        return f"https://{normalized_override}"

    if not workspace:
        raise ValueError("workspace is required")

    cache_key = get_workspace_frontend_base_url_cache_key(workspace.id)
    cached = cache.get(cache_key)
    if cached:
        return cached

    primary = workspace.domains.filter(
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        is_primary=True,
    ).first()
    if primary:
        value = f"https://{primary.hostname}"
        cache.set(cache_key, value, cache_ttl())
        return value

    system_default = workspace.domains.filter(kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT).first()
    if system_default:
        value = f"https://{system_default.hostname}"
        cache.set(cache_key, value, cache_ttl())
        return value

    raise ValueError(f"Workspace {workspace.id} does not have a public frontend domain configured")


def compute_system_default_hostname(workspace, cluster) -> str:
    if not workspace or not cluster or not getattr(cluster, "frontend_base_url", ""):
        return ""
    parsed = urlparse(cluster.frontend_base_url)
    netloc = normalize_hostname(parsed.netloc or parsed.path or "")
    if not netloc or not workspace.slug:
        return ""
    return normalize_hostname(f"{workspace.slug}.{netloc}")


def ensure_system_default_workspace_domain(workspace):
    profile = getattr(workspace, "platform_profile", None)
    cluster = getattr(profile, "cluster", None) if profile else None
    hostname = compute_system_default_hostname(workspace, cluster)
    if not hostname:
        return None

    stale = WorkspaceDomain.objects.filter(
        workspace=workspace,
        kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT,
    ).exclude(hostname=hostname)
    if stale.exists():
        stale.delete()

    domain, _ = WorkspaceDomain.objects.update_or_create(
        workspace=workspace,
        kind=WorkspaceDomain.KIND_SYSTEM_DEFAULT,
        defaults={
            "hostname": hostname,
            "verification_status": WorkspaceDomain.VERIFICATION_VERIFIED,
            "ssl_status": WorkspaceDomain.SSL_NONE,
            "is_primary": False,
        },
    )
    return domain


def upsert_custom_workspace_domain(workspace, hostname, *, is_primary=False, verification_status=None, ssl_status=None):
    normalized = normalize_hostname(hostname)
    if not normalized:
        return None
    if is_primary:
        WorkspaceDomain.objects.filter(
            workspace=workspace,
            kind=WorkspaceDomain.KIND_CUSTOM,
            is_primary=True,
        ).exclude(hostname=normalized).update(is_primary=False)
    defaults = {
        "kind": WorkspaceDomain.KIND_CUSTOM,
        "is_primary": bool(is_primary),
    }
    if verification_status is not None:
        defaults["verification_status"] = verification_status
    elif is_primary:
        # clean() requires verified status when is_primary; bootstrap paths (e.g. init localhost) omit this.
        defaults["verification_status"] = WorkspaceDomain.VERIFICATION_VERIFIED
    if ssl_status is not None:
        defaults["ssl_status"] = ssl_status

    domain, _ = WorkspaceDomain.objects.update_or_create(
        hostname=normalized,
        defaults={"workspace": workspace, **defaults},
    )
    return domain

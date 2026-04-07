# -*- coding: utf-8 -*-
import secrets
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class WorkspacePlatformProfile(models.Model):
    """
    Extended platform-level metadata for a Workspace.
    Stores cluster assignment, API keys, custom domain, and suspension info.
    """
    SSL_STATUS_CHOICES = [
        ("none", _("None")),
        ("pending", _("Pending")),
        ("active", _("Active")),
        ("failed", _("Failed")),
    ]

    workspace = models.OneToOneField(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="platform_profile",
        null=True,
        blank=True,
    )

    remote_workspace_uuid = models.UUIDField(
        _("Remote Workspace UUID"),
        null=True,
        blank=True,
        help_text=_("UUID of the workspace on the remote cluster/workspace instance"),
    )

    cluster = models.ForeignKey(
        "platform.Cluster",
        verbose_name=_("Cluster"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workspaces",
    )
    region = models.CharField(_("Region"), max_length=20, default="us")
    
    # API Keys
    platform_api_key = models.CharField(_("Platform API Key"), max_length=64, blank=True)
    agent_api_key = models.CharField(_("Agent API Key"), max_length=64, blank=True)

    # Suspension / Deletion scheduling
    suspended_at = models.DateTimeField(_("Suspended At"), null=True, blank=True)
    scheduled_deletion_at = models.DateTimeField(_("Scheduled Deletion At"), null=True, blank=True)

    # Custom domain
    custom_domain = models.CharField(_("Custom Domain"), max_length=255, blank=True)
    ssl_status = models.CharField(
        _("SSL Status"), max_length=20, choices=SSL_STATUS_CHOICES, default="none"
    )

    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Workspace Platform Profile")
        verbose_name_plural = _("Workspace Platform Profiles")

    def __str__(self):
        if self.remote_workspace_uuid:
            return f"Platform Profile: {self.remote_workspace_uuid}"
        return f"Platform Profile #{self.pk}"

    def generate_api_keys(self):
        """Generate fresh platform and agent API keys."""
        self.platform_api_key = secrets.token_urlsafe(48)[:64]
        self.agent_api_key = secrets.token_urlsafe(48)[:64]

    @property
    def is_suspended(self):
        return self.suspended_at is not None

    @property
    def is_scheduled_for_deletion(self):
        return self.scheduled_deletion_at is not None


class WorkspaceSSOConfig(models.Model):
    """
    SSO configuration for a Workspace.
    Maps an email domain to an SSO provider so login can be routed automatically.
    """
    PROTOCOL_CHOICES = [
        ("google_oauth2", _("Google Workspace OAuth2")),
        ("azure_oidc", _("Azure AD / Entra ID OIDC")),
        ("saml2", _("Generic SAML 2.0")),
        ("oidc", _("Generic OIDC")),
    ]

    workspace = models.ForeignKey(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="sso_configs",
    )
    email_domain = models.CharField(_("Email Domain"), max_length=100, unique=True)
    protocol = models.CharField(_("Protocol"), max_length=20, choices=PROTOCOL_CHOICES)

    # OAuth2 / OIDC credentials
    client_id = models.CharField(_("Client ID"), max_length=200, blank=True)
    client_secret = models.CharField(_("Client Secret"), max_length=200, blank=True)

    # Azure-specific
    tenant_id = models.CharField(_("Tenant ID"), max_length=100, blank=True)

    # SAML2-specific
    saml_metadata_url = models.URLField(_("SAML Metadata URL"), blank=True)

    # Generic OIDC
    oidc_discovery_url = models.URLField(_("OIDC Discovery URL"), blank=True)

    # Provisioning
    default_role = models.CharField(_("Default Role"), max_length=50, default="staff")
    role_mapping = models.JSONField(_("Role Mapping"), default=dict, blank=True)
    # Example: {"admin": "admin", "member": "staff"}

    # Behavior
    enforce_sso = models.BooleanField(_("Enforce SSO"), default=False)
    auto_provision = models.BooleanField(_("Auto Provision"), default=True)
    is_active = models.BooleanField(_("Active"), default=True)

    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Workspace SSO Config")
        verbose_name_plural = _("Workspace SSO Configs")
        ordering = ["email_domain"]
        indexes = [
            models.Index(fields=["workspace", "is_active"]),
        ]

    def __str__(self):
        return f"{self.email_domain} → {self.get_protocol_display()}"


class PlatformMembership(models.Model):
    """
    Records which Platform User has access to which WorkspacePlatformProfile,
    and what role they have in that remote workspace.

    This is the Platform-side record of the user↔workspace relationship.
    The actual permissions live in the Workspace instance (StaffMember),
    but Platform needs this to:
    1. Show users their workspace list after login
    2. Gate Token Exchange (only members can exchange tokens)
    3. Track the remote workspace UUID for routing
    """
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("staff", "Staff"),        
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_memberships",
        verbose_name=_("User"),
    )
    profile = models.ForeignKey(
        "platform.WorkspacePlatformProfile",
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Workspace Profile"),
    )
    role = models.CharField(_("Role"), max_length=20, choices=ROLE_CHOICES, default="staff")

    is_active = models.BooleanField(_("Active"), default=True)
    is_default = models.BooleanField(_("Default"), default=False)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Platform Membership")
        verbose_name_plural = _("Platform Memberships")
        unique_together = ("user", "profile")
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["profile", "is_active"]),
        ]

    def __str__(self):
        label = self.profile.remote_workspace_uuid or f"profile #{self.profile_id}"
        return f"{self.user} → {label} ({self.role})"


class PlatformSSOCode(models.Model):
    """
    One-time SSO code for cross-domain workspace login.

    Flow:
      1. Platform generates a short-lived code bound to a user + workspace
      2. Browser is redirected to the workspace domain with ?code=...
      3. Workspace frontend exchanges the code for a JWT via sso/exchange
      4. Code is marked used immediately — replay is rejected
    """
    SSO_CODE_TTL = getattr(settings, "SSO_CODE_TTL_SECONDS", 300)

    code = models.CharField(
        _("SSO Code"), max_length=128, unique=True, db_index=True,
    )
    workspace = models.ForeignKey(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="sso_codes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("User"),
        on_delete=models.CASCADE,
        related_name="sso_codes",
    )
    expires_at = models.DateTimeField(_("Expires At"), db_index=True)
    used_at = models.DateTimeField(_("Used At"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    created_by_ip = models.GenericIPAddressField(_("Created By IP"), null=True, blank=True)
    next_url = models.CharField(_("Next URL"), max_length=512, blank=True, default="/admin")
    redirect_domain = models.CharField(
        _("Redirect Domain"), max_length=255, blank=True,
        help_text=_("Target domain used for the redirect URL"),
    )

    class Meta:
        verbose_name = _("Platform SSO Code")
        verbose_name_plural = _("Platform SSO Codes")
        indexes = [
            models.Index(fields=["workspace", "user"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"SSO {self.code[:8]}… → {self.workspace} ({self.user})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = secrets.token_urlsafe(48)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(seconds=self.SSO_CODE_TTL)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_usable(self):
        return not self.is_expired and not self.is_used

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

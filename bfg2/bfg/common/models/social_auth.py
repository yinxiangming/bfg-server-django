# -*- coding: utf-8 -*-
"""
Social-login credentials: one platform-wide default, overridable per workspace.

Google validates the *origin* the button renders on and the redirect URI it
returns to against the OAuth client, and the consent screen shows the client
owner's app name. A shop that wants its own branding on that screen, or One Tap
on its own domain, therefore needs its own OAuth client.

Most shops do not. The redirect flow only ever returns to *our* API domain, so a
single platform client — registered once for surlex.co.nz — carries every
workspace that has not registered one of its own. That is what a row with no
workspace is: the platform default. One Tap is the exception, because it renders
in the storefront's own page and Google checks that origin (with no wildcard
support), so a custom domain needs either its own client or its origin added to
the platform client.

The field set deliberately mirrors allauth's ``SocialApp`` (client_id / secret /
key / settings) so :class:`config.social_adapter.WorkspaceSocialAccountAdapter`
can turn a row into one without a translation layer.

Not to be confused with :class:`bfg.platform.models.WorkspaceSSOConfig`, which
routes *staff* login by email domain for enterprise SSO. This is the
consumer-facing storefront sign-in that allauth drives.
"""
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class SocialAuthConfig(models.Model):
    """One OAuth application for one provider, owned by a workspace or by the platform."""

    PROVIDER_GOOGLE = 'google'
    PROVIDER_FACEBOOK = 'facebook'
    PROVIDER_APPLE = 'apple'
    PROVIDER_CHOICES = [
        (PROVIDER_GOOGLE, _("Google")),
        (PROVIDER_FACEBOOK, _("Facebook")),
        (PROVIDER_APPLE, _("Apple")),
    ]

    # What each provider must have before it can be offered as a login button.
    # Apple signs its client secret with a private key, so it needs two more
    # fields than the plain OAuth2 pair. Kept next to the model rather than in
    # the view so the API, the adapter and the admin all agree on "configured".
    REQUIRED_FIELDS = {
        PROVIDER_GOOGLE: ('client_id', 'secret'),
        PROVIDER_FACEBOOK: ('client_id', 'secret'),
        PROVIDER_APPLE: ('client_id', 'secret', 'key', 'certificate_key'),
    }

    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='social_auth_configs',
        verbose_name=_("Workspace"),
        null=True,
        blank=True,
        help_text=_("Empty means the platform default, inherited by every workspace."),
    )
    provider = models.CharField(_("Provider"), max_length=30, choices=PROVIDER_CHOICES)
    client_id = models.CharField(
        _("Client ID"), max_length=191,
        help_text=_("OAuth client ID / App ID. Public — the browser needs it."),
    )
    secret = models.CharField(_("Client Secret"), max_length=191, blank=True)
    # Apple's key ID. Unused by Google and Facebook.
    key = models.CharField(_("Key"), max_length=191, blank=True)
    # Provider-specific extras, using allauth's own SocialApp.settings shape.
    # Apple's ``certificate_key`` (the .p8 private key) lives here: allauth 65
    # warns when it is passed at the top level and expects it under settings.
    settings = models.JSONField(_("Extra Settings"), default=dict, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Social Auth Config")
        verbose_name_plural = _("Social Auth Configs")
        ordering = ['provider']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'provider'],
                name='uniq_social_auth_config_workspace_provider',
            ),
            # NULLs never collide in a plain unique index, so the one-default
            # rule needs its own constraint. MySQL declines conditional unique
            # constraints (system check W036) and leaves this to the callers —
            # the serializer and the admin both check before saving.
            models.UniqueConstraint(
                fields=['provider'],
                condition=models.Q(workspace__isnull=True),
                name='uniq_social_auth_config_platform_provider',
            ),
        ]
        indexes = [
            models.Index(fields=['workspace', 'is_active']),
        ]

    def __str__(self):
        owner = self.workspace_id or 'platform default'
        return f"{self.get_provider_display()} ({owner})"

    @property
    def is_platform_default(self):
        return self.workspace_id is None

    def field_value(self, name):
        """Read a required field whether it is a column or a settings key."""
        if name == 'certificate_key':
            return (self.settings or {}).get('certificate_key') or ''
        return getattr(self, name, '') or ''

    @property
    def is_configured(self):
        """True when every credential this provider needs is filled in.

        ``is_active`` is a separate switch: an admin turning a provider off
        should not have to clear the credentials to do it.
        """
        required = self.REQUIRED_FIELDS.get(self.provider) or ()
        return bool(required) and all(str(self.field_value(f)).strip() for f in required)

    @property
    def is_usable(self):
        return self.is_active and self.is_configured

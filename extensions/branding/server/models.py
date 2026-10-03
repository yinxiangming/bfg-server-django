# -*- coding: utf-8 -*-
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bfg.common.extensions import (
    ACTIVATION_WORKSPACE_OWNER,
    VISIBILITY_PUBLIC,
    registry,
)
from bfg.common.extensions.storefront_skins import validate_storefront_skin
from bfg.common.models import WorkspaceExtension


class BrandPortalProfile(models.Model):
    """Runtime configuration for one workspace acting as a branded portal."""

    workspace = models.OneToOneField(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='brand_portal_profile',
        verbose_name=_('Workspace'),
    )
    public_id = models.UUIDField(_('Public ID'), default=uuid.uuid4, unique=True, editable=False)
    registration_enabled = models.BooleanField(_('Registration enabled'), default=False)
    provisioning_extensions = models.JSONField(_('Provisioning extensions'), default=list, blank=True)
    default_theme = models.CharField(_('Default theme'), max_length=64, blank=True)
    default_plan = models.CharField(_('Default plan'), max_length=64, blank=True)
    default_country = models.CharField(_('Default country'), max_length=2, blank=True)
    default_currency = models.CharField(_('Default currency'), max_length=3, blank=True)
    default_language = models.CharField(_('Default language'), max_length=16, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('Created by'),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('Updated by'),
    )
    created_at = models.DateTimeField(_('Created at'), default=timezone.now)
    updated_at = models.DateTimeField(_('Updated at'), auto_now=True)

    class Meta:
        verbose_name = _('Brand portal profile')
        verbose_name_plural = _('Brand portal profiles')
        ordering = ['workspace_id']

    def clean_fields(self, exclude=None):
        self.default_theme = (self.default_theme or '').strip().lower()
        self.default_country = (self.default_country or '').strip().upper()
        self.default_currency = (self.default_currency or '').strip().upper()
        self.default_language = (self.default_language or '').strip().lower()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        errors = {}
        if self.registration_enabled and not WorkspaceExtension.all_objects.filter(
            workspace_id=self.workspace_id,
            key='brand_portal',
            status=WorkspaceExtension.STATUS_ACTIVE,
        ).exists():
            errors['registration_enabled'] = _(
                'Activate the brand_portal extension before enabling registration.'
            )

        try:
            self.provisioning_extensions = self._clean_extension_keys(
                self.provisioning_extensions
            )
        except ValidationError as exc:
            errors['provisioning_extensions'] = exc.messages

        if 'provisioning_extensions' not in errors:
            try:
                self.default_theme = validate_storefront_skin(
                    self.default_theme,
                    extension_keys=self.provisioning_extensions,
                )
            except ValueError:
                errors['default_theme'] = [_('Unsupported storefront theme.')]

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _clean_extension_keys(value):
        if not isinstance(value, list):
            raise ValidationError(_('Provisioning extensions must be a JSON list.'))
        if len(value) > 32:
            raise ValidationError(_('A portal may provision at most 32 extensions.'))
        cleaned = []
        for key in value:
            if not isinstance(key, str) or not key.strip():
                raise ValidationError(_('Every provisioning extension must be a non-empty key.'))
            key = key.strip()
            if key in cleaned:
                raise ValidationError(_('Provisioning extension keys must be unique.'))
            manifest = registry.get_manifest(key)
            if manifest is None:
                raise ValidationError(_('%(key)s is not a deployed extension.') % {'key': key})
            if (
                not manifest.is_activatable
                or manifest.visibility != VISIBILITY_PUBLIC
                or manifest.activation_policy != ACTIVATION_WORKSPACE_OWNER
            ):
                raise ValidationError(
                    _('%(key)s is not a public workspace extension that a portal may provision.')
                    % {'key': key}
                )
            cleaned.append(key)
        return cleaned

    def __str__(self):
        return f'Brand portal for workspace {self.workspace_id}'


class BrandPortalRegistration(models.Model):
    """Bind a registered account and trusted callback origin to one portal."""

    portal_workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='brand_portal_registrations',
        verbose_name=_('Portal workspace'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='brand_portal_registrations',
        verbose_name=_('User'),
    )
    callback_origin = models.URLField(_('Callback origin'), max_length=255)
    verified_at = models.DateTimeField(_('Verified at'), null=True, blank=True)
    created_at = models.DateTimeField(_('Created at'), default=timezone.now)
    updated_at = models.DateTimeField(_('Updated at'), auto_now=True)

    class Meta:
        verbose_name = _('Brand portal registration')
        verbose_name_plural = _('Brand portal registrations')
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['portal_workspace', 'user'],
                name='brand_portal_registration_user_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['portal_workspace', 'verified_at'],
                name='brand_portal_reg_verified_idx',
            ),
        ]

    def __str__(self):
        return f'{self.user_id} @ portal workspace {self.portal_workspace_id}'


class BrandPortalProvisioning(models.Model):
    """Immutable source and retry identity for one portal provisioning request."""

    STATUS_PENDING = 'pending'
    STATUS_PROVISIONING = 'provisioning'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_PENDING, _('Pending')),
        (STATUS_PROVISIONING, _('Provisioning')),
        (STATUS_COMPLETED, _('Completed')),
        (STATUS_FAILED, _('Failed')),
    )

    portal_workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='brand_portal_provisionings',
        verbose_name=_('Portal workspace'),
    )
    target_workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='brand_portal_sources',
        verbose_name=_('Target workspace'),
    )
    sso_code = models.OneToOneField(
        'platform.PlatformSSOCode',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='brand_portal_provisioning',
        verbose_name=_('SSO code'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='brand_portal_provisionings',
        verbose_name=_('User'),
    )
    idempotency_key = models.CharField(_('Idempotency key'), max_length=128)
    profile_snapshot = models.JSONField(_('Profile snapshot'), default=dict, blank=True)
    status = models.CharField(
        _('Status'), max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    error_code = models.CharField(_('Error code'), max_length=64, blank=True)
    error_detail = models.TextField(_('Error detail'), blank=True)
    created_at = models.DateTimeField(_('Created at'), default=timezone.now)
    updated_at = models.DateTimeField(_('Updated at'), auto_now=True)
    completed_at = models.DateTimeField(_('Completed at'), null=True, blank=True)

    class Meta:
        verbose_name = _('Brand portal provisioning')
        verbose_name_plural = _('Brand portal provisionings')
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['portal_workspace', 'idempotency_key'],
                name='brand_portal_workspace_idempotency_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['portal_workspace', 'status', '-created_at'],
                name='brand_portal_status_time_idx',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        self.idempotency_key = (self.idempotency_key or '').strip()
        if not self.idempotency_key:
            errors['idempotency_key'] = _('Idempotency key cannot be blank.')
        if self.status == self.STATUS_COMPLETED:
            if self.target_workspace_id is None:
                errors['target_workspace'] = _('A completed provisioning must name its target workspace.')
            if self.completed_at is None:
                errors['completed_at'] = _('A completed provisioning must record when it completed.')
            if self.sso_code_id is None:
                errors['sso_code'] = _('A completed provisioning must have an SSO code.')
        elif self.completed_at is not None:
            errors['completed_at'] = _('Only a completed provisioning may have a completion time.')
        if self.status == self.STATUS_FAILED and not self.error_code:
            errors['error_code'] = _('A failed provisioning must have a stable error code.')
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.idempotency_key} @ portal workspace {self.portal_workspace_id}'

# -*- coding: utf-8 -*-
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bfg.common.managers import TenantScopedModel


class WorkspaceExtension(TenantScopedModel):
    """Whether one workspace uses one extension, and in which state.

    A workspace with no row for an extension does not use it. Deactivation keeps the
    row: it holds the workspace's configuration, who last changed the state and, once
    the extension's data has been archived, where that archive lives.
    """

    STATUS_ACTIVE = 'active'
    # Stopped because the workspace's entitlement ended; data and configuration are kept.
    STATUS_PAUSED = 'paused'
    # Switched off on purpose; data and configuration are kept.
    STATUS_INACTIVE = 'inactive'
    STATUS_ARCHIVING = 'archiving'
    STATUS_ARCHIVED = 'archived'
    STATUS_RESTORING = 'restoring'
    STATUS_CHOICES = (
        (STATUS_ACTIVE, _('Active')),
        (STATUS_PAUSED, _('Paused')),
        (STATUS_INACTIVE, _('Inactive')),
        (STATUS_ARCHIVING, _('Archiving')),
        (STATUS_ARCHIVED, _('Archived')),
        (STATUS_RESTORING, _('Restoring')),
    )

    workspace = models.ForeignKey(
        'common.Workspace',
        on_delete=models.CASCADE,
        related_name='extension_records',
        verbose_name=_('Workspace'),
    )
    key = models.CharField(_('Extension'), max_length=64)
    status = models.CharField(_('Status'), max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    status_reason = models.CharField(_('Status reason'), max_length=64, blank=True)
    config = models.JSONField(_('Configuration'), default=dict, blank=True)
    status_changed_at = models.DateTimeField(_('Status changed at'), default=timezone.now)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('Status changed by'),
    )
    activated_at = models.DateTimeField(_('Last activated at'), null=True, blank=True)
    archive_location = models.CharField(_('Archive location'), max_length=512, blank=True)

    created_at = models.DateTimeField(_('Created at'), default=timezone.now)
    updated_at = models.DateTimeField(_('Updated at'), auto_now=True)

    class Meta:
        verbose_name = _('Workspace extension')
        verbose_name_plural = _('Workspace extensions')
        ordering = ['key']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'key'], name='common_workspace_extension_uniq'),
        ]
        indexes = [
            models.Index(fields=['key', 'status']),
        ]
        base_manager_name = 'all_objects'

    def __str__(self):
        return f'{self.key} @ workspace {self.workspace_id} ({self.status})'

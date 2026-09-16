# -*- coding: utf-8 -*-
"""Tables shaped like the ones an extension owns, for the archive suite.

Real enough to exercise what archiving has to get right — a workspace column on every
table, a child that cascades, a many-to-many with a join table Django made, and a table
with no workspace of its own — without tying the suite to whichever extensions a
deployment happens to install.
"""

from django.db import models

from bfg.common.managers import TenantScopedModel


class ArchiveTag(TenantScopedModel):
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='+')
    label = models.CharField(max_length=32)

    class Meta:
        app_label = 'extension_data_tests'
        base_manager_name = 'all_objects'


class ArchiveNote(TenantScopedModel):
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='+')
    title = models.CharField(max_length=64)
    body = models.TextField(blank=True)
    tags = models.ManyToManyField(ArchiveTag, blank=True, related_name='notes')

    class Meta:
        app_label = 'extension_data_tests'
        base_manager_name = 'all_objects'


class ArchiveComment(TenantScopedModel):
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='+')
    note = models.ForeignKey(ArchiveNote, on_delete=models.CASCADE, related_name='comments')
    body = models.CharField(max_length=128)

    class Meta:
        app_label = 'extension_data_tests'
        base_manager_name = 'all_objects'


class ArchiveMention(models.Model):
    """A table with no workspace of its own that points at one that has.

    Two things at once: listed among an extension's tables it cannot be archived, since
    nothing says whose rows these are; left off the list it is something a delete would
    reach into, which is equally a reason not to archive.
    """

    note = models.ForeignKey(ArchiveNote, on_delete=models.CASCADE, related_name='mentions')
    note_text = models.CharField(max_length=64, blank=True)

    class Meta:
        app_label = 'extension_data_tests'

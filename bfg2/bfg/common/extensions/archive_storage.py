# -*- coding: utf-8 -*-
"""
Where an extension's archived data is written — and everywhere it must not be.

An archive is the only copy left of a workspace's data once the rows have been
deleted, so it goes to storage the deployment has set aside for it and nowhere
else. ``BFG_EXTENSION_ARCHIVE_STORAGE`` names an alias in ``STORAGES``; the bucket,
the credentials and the region are that alias's business, which is what keeps this
module free of any one provider. ``BFG_EXTENSION_ARCHIVE_PREFIX`` is the prefix
every key is written under, so one bucket can hold several deployments.

**Unset, archiving does not run at all.** Nothing is exported and nothing is
deleted; the sweep says so and stops. That is deliberate: a deployment that has
not decided where archives live has not decided that data may be deleted either.

The alias is checked before it is used, and refused when it is, or might be, the
storage the deployment serves media from: the same alias as ``default``, the same
storage object, the same bucket, a filesystem path that overlaps ``MEDIA_ROOT``, or
anything carrying a ``custom_domain``, which is how a bucket is put behind a CDN. An
archive holds every row of a table verbatim, and a public URL to one is a data breach
rather than an inconvenience, so each of these is an error and never a warning.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import posixpath

from django.conf import settings
from django.core.files.storage import InvalidStorageError, storages

logger = logging.getLogger(__name__)

#: Prefix used when the deployment names none.
DEFAULT_PREFIX = 'extension-archives'

#: Aliases that are the deployment's own media, whatever they are configured with.
SERVED_ALIASES = ('default', 'staticfiles')


class ArchiveNotConfigured(Exception):
    """Archiving has nowhere it may write, so the feature is off.

    ``reason`` is meant to be read by whoever runs the deployment: it says which
    setting is missing or which check the configured storage did not pass.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def storage_alias() -> str:
    return (getattr(settings, 'BFG_EXTENSION_ARCHIVE_STORAGE', '') or '').strip()


def prefix() -> str:
    configured = (getattr(settings, 'BFG_EXTENSION_ARCHIVE_PREFIX', '') or '').strip().strip('/')
    return configured or DEFAULT_PREFIX


def archive_storage():
    """The storage archives are written to, or ``ArchiveNotConfigured`` saying why not."""
    alias = storage_alias()
    if not alias:
        raise ArchiveNotConfigured(
            'BFG_EXTENSION_ARCHIVE_STORAGE names no storage, so nothing may be archived. '
            'Point it at a STORAGES alias for private storage that is not served to anyone.'
        )
    if alias in SERVED_ALIASES:
        raise ArchiveNotConfigured(
            f'BFG_EXTENSION_ARCHIVE_STORAGE is {alias!r}, which is the storage this deployment '
            f'serves. Archives must go to storage of their own.'
        )
    try:
        store = storages[alias]
    except InvalidStorageError:
        raise ArchiveNotConfigured(
            f'BFG_EXTENSION_ARCHIVE_STORAGE names {alias!r}, which is not in STORAGES.'
        ) from None
    _refuse_served_storage(store, alias)
    return store


def is_configured() -> bool:
    """Whether archiving has somewhere to write. Never raises."""
    try:
        archive_storage()
    except ArchiveNotConfigured:
        return False
    return True


def why_unconfigured() -> str:
    """The reason archiving is off, or an empty string when it is on."""
    try:
        archive_storage()
    except ArchiveNotConfigured as unconfigured:
        return unconfigured.reason
    return ''


def _refuse_served_storage(store, alias: str) -> None:
    # Everything that would put an archive where somebody can fetch it. Each check is
    # cheap and reads configuration only, so it runs on every archive rather than once.
    served = storages['default']
    if store is served:
        raise ArchiveNotConfigured(
            f'BFG_EXTENSION_ARCHIVE_STORAGE alias {alias!r} resolves to the same storage as '
            f'"default", which this deployment serves.'
        )
    if getattr(store, 'custom_domain', None):
        raise ArchiveNotConfigured(
            f'The storage alias {alias!r} has a custom_domain, which is how a bucket is put '
            f'behind a CDN. Archives are not served; configure the alias without one.'
        )

    bucket = _bucket_of(store)
    if bucket is not None and bucket == _bucket_of(served):
        # The bucket, not the bucket and prefix: whether an object is public is decided by
        # the bucket's policy, and a prefix of its own inside a world-readable bucket is a
        # world-readable archive. Give archives a bucket.
        raise ArchiveNotConfigured(
            f'The storage alias {alias!r} writes to {bucket}, which is the bucket this deployment '
            f'serves media from. Archives need a bucket of their own.'
        )

    overlap = _filesystem_overlap(store)
    if overlap:
        raise ArchiveNotConfigured(
            f'The storage alias {alias!r} writes to {overlap}, which is served as media. '
            f'Archives need a directory outside MEDIA_ROOT.'
        )


def _bucket_of(store):
    """The bucket an object store writes to, or ``None`` for anything else."""
    return getattr(store, 'bucket_name', None) or None


def _filesystem_overlap(store) -> str:
    """The media directory ``store`` writes inside of, or an empty string."""
    location = getattr(store, 'location', None)
    # An object store's ``location`` is a key prefix, not a path; it is compared as part
    # of the bucket instead.
    if not location or _bucket_of(store) is not None:
        return ''
    media_root = str(getattr(settings, 'MEDIA_ROOT', '') or '')
    if not media_root:
        return ''
    archive_path = os.path.realpath(str(location))
    media_path = os.path.realpath(media_root)
    if archive_path == media_path or _inside(archive_path, media_path) or _inside(media_path, archive_path):
        return media_path
    return ''


def _inside(path: str, directory: str) -> bool:
    return path.startswith(directory.rstrip(os.sep) + os.sep)


# ── Where one archive lives ──────────────────────────────────────────


def extension_root(workspace_id: int, key: str) -> str:
    """Every archive this workspace has of this extension lives under here."""
    return posixpath.join(prefix(), f'workspace-{int(workspace_id)}', key)


def archive_directory(workspace_id: int, key: str, at) -> str:
    """The directory one archive taken at ``at`` is written to.

    The timestamp is in UTC and to the second, so a workspace that stops and
    restarts an extension over the years keeps every archive it ever had rather
    than overwriting the last one.
    """
    stamp = at.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return posixpath.join(extension_root(workspace_id, key), stamp)

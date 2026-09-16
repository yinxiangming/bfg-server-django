# -*- coding: utf-8 -*-
"""
Archiving the data of an extension a workspace has stopped using, and bringing it back.

A workspace that switches an extension off keeps its rows: they are what makes
switching it on again the whole of the work. After long enough — ``archive_after_days``,
counted from the moment the extension became ``inactive`` or ``paused`` — those rows are
worth more as a file than as tables, and this is what moves them: every table the
extension's manifest declares is written to private storage as JSON Lines, read back and
checked, and only then deleted.

**The delete is the dangerous half, so everything here is arranged around refusing it.**
Nothing is deleted that was not exported and read back byte for byte; nothing outside the
manifest's ``data_models`` is touched, which the delete itself is made to prove by
reporting what it deleted and being rolled back when that is not exactly what was
exported; and no row of another workspace is read, exported or deleted, because every
table is selected by its ``workspace`` column and a table without one is refused rather
than guessed at. When any of that does not hold the extension goes back to the status it
had, with the reason on the record, and the rows stay where they are.

Coming back is the same in reverse and just as careful. An archive written against an
older schema is refused unless the manifest offers a converter for the app whose
migrations have moved, because loading rows into a table that has changed shape is how an
archive turns into corruption. Loading is keyed by primary key, so restoring the same
archive twice writes the same rows twice rather than a second copy of them, and a primary
key that now belongs to a different workspace stops the restore instead of overwriting
somebody else's row.

Neither deployment runs a scheduler, so nothing here happens by itself: the sweep is the
``archive_unused_extensions`` management command, and a restore is somebody asking for one.
Both are safe to run twice.

Statuses, and what a failure leaves behind::

    inactive/paused ──archive──> archiving ──> archived
                          └── failed ──> inactive/paused, status_reason says why
    archived ──restore──> restoring ──> active
                   └── failed ──> archived, status_reason says why

An interrupted run (the process died between the two) leaves ``archiving`` or
``restoring`` behind, and the next sweep puts it back — see ``release_stuck``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import posixpath
import tempfile
from collections import Counter
from typing import Dict, List, Optional

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.db.models import Prefetch
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from bfg.common.extensions import registry
from bfg.common.extensions.archive_storage import (  # noqa: F401  (re-exported for callers)
    ArchiveNotConfigured,
    archive_directory,
    archive_storage,
    is_configured,
    why_unconfigured,
)
from bfg.common.extensions.services import ExtensionError, invalidate

logger = logging.getLogger(__name__)

#: Bumped when the layout of an archive changes in a way an older reader cannot follow.
FORMAT_VERSION = 1
MANIFEST_NAME = 'manifest.json'
CHECKSUM_ALGORITHM = 'sha256'
#: Read back in pieces rather than whole: an archive is as large as the tables were.
CHUNK = 1024 * 1024

#: ``status_reason`` while a run is going on, and after one has finished or failed. Short
#: because the column is, and stable because a console may key off them; the sentence a
#: person reads is in ``archive_state``.
REASON_ARCHIVING = 'archiving'
REASON_ARCHIVED = 'archived'
REASON_ARCHIVE_FAILED = 'archive_failed'
REASON_ARCHIVE_INTERRUPTED = 'archive_interrupted'
REASON_RESTORING = 'restoring'
REASON_RESTORE_FAILED = 'restore_failed'
REASON_RESTORE_INTERRUPTED = 'restore_interrupted'

#: How long a run may be in flight before a sweep decides nothing is running it.
DEFAULT_STUCK_MINUTES = 60


class ArchiveRefused(ExtensionError):
    """Something that would have to be guessed at to go on. ``code`` is stable for clients."""


def _extension_model():
    from bfg.common.models import WorkspaceExtension

    return WorkspaceExtension


def _actor(user):
    return user if user is not None and getattr(user, 'is_authenticated', False) else None


def _manifest_of(key: str):
    manifest = registry.get_manifest(key)
    if manifest is None:
        raise ArchiveRefused('unknown_extension', f'No extension named {key!r} is deployed.')
    if not manifest.is_activatable:
        raise ArchiveRefused(
            'not_activatable', f'{key} is always available, so it has nothing to archive.'
        )
    return manifest


def _record(workspace, key):
    WorkspaceExtension = _extension_model()

    record = WorkspaceExtension.all_objects.filter(workspace=workspace, key=key).first()
    if record is None:
        raise ArchiveRefused('not_used', f'This workspace has never used {key}.')
    return record


# ── What may be archived ─────────────────────────────────────────────


def archivable_models(manifest) -> List:
    """The models ``manifest`` declares, in an order that puts a parent before its children.

    Every one of them must carry a ``workspace`` relation. That is the whole of how this
    module knows which rows belong to the workspace being archived, and a table without
    one would leave it choosing between archiving another workspace's rows and deleting
    rows it never exported — so it is refused, and the extension keeps its data until its
    manifest says which column to read.
    """
    models = []
    for label in manifest.data_models:
        try:
            model = apps.get_model(label)
        except (LookupError, ValueError):
            raise ArchiveRefused(
                'unknown_model',
                f'{manifest.key} declares the table {label!r}, which this deployment has no '
                f'model for.',
                model=label,
            ) from None
        field = next(
            (
                candidate
                for candidate in model._meta.concrete_fields
                if candidate.name == 'workspace' and candidate.is_relation
            ),
            None,
        )
        if field is None:
            raise ArchiveRefused(
                'unscoped_model',
                f'{model._meta.label} has no workspace relation, so there is no way to tell which '
                f'of its rows belong to this workspace. Give it one, or take it out of '
                f'{manifest.key}\'s data_models.',
                model=model._meta.label,
            )
        models.append(model)
    if not models:
        raise ArchiveRefused(
            'no_data_models', f'{manifest.key} declares no tables of its own, so it has nothing to archive.'
        )
    return _parents_first(models)


def _parents_first(models: List) -> List:
    """``models`` ordered so that a model comes after the ones it points at.

    Rows are written and loaded in this order and deleted in the reverse of it, which is
    what keeps a restore from inserting a child before its parent on a database that
    checks foreign keys as it goes.
    """
    labels = {model._meta.label for model in models}

    def pointed_at(model):
        # Foreign keys and many-to-many alike: a row is written with the keys of what it
        # joins to, so both have to be there before it is loaded.
        related = (
            field.related_model
            for field in list(model._meta.concrete_fields) + list(model._meta.many_to_many)
            if field.is_relation and field.related_model is not None
        )
        return {
            other._meta.label
            for other in related
            if other._meta.label in labels and other._meta.label != model._meta.label
        }

    waits_for = {model._meta.label: pointed_at(model) for model in models}
    remaining = list(models)
    ordered: List = []
    placed = set()
    while remaining:
        ready = [model for model in remaining if not waits_for[model._meta.label] - placed]
        if not ready:
            # A cycle between the extension's own tables. Nothing here can order those,
            # and the declared order is as good a guess as any; a database that checks
            # foreign keys row by row will refuse the restore, which is the right answer.
            ordered.extend(remaining)
            break
        for model in ready:
            ordered.append(model)
            placed.add(model._meta.label)
        remaining = [model for model in remaining if model._meta.label not in placed]
    return ordered


def _through_labels(models) -> set:
    """Labels of the join tables Django made for the many-to-many fields of ``models``.

    Their rows go when the rows they join go, and they are written back from the field on
    the model that declares them, so they are expected among what a delete reports without
    being tables the manifest has to list.
    """
    labels = set()
    for model in models:
        for field in model._meta.many_to_many:
            through = field.remote_field.through
            if through is not None and through._meta.auto_created:
                labels.add(through._meta.label)
    return labels


def refuse_outside_references(workspace, models) -> None:
    """Refuse when anything outside the manifest points at the rows about to be archived.

    A foreign key from a table the extension does not own is how a delete reaches past
    what was exported: ``CASCADE`` takes the other table's rows with it, ``SET_NULL``
    empties a column in them, ``PROTECT`` stops the delete halfway. Rather than work out
    which, this asks whether anything actually points at this workspace's rows, and stops
    the archive while something does. Nothing is refused for a relation that exists in the
    schema but holds no rows, so an extension a shop never wired into anything archives
    normally.
    """
    owned = {model._meta.label for model in models}
    for model in models:
        for relation in model._meta.related_objects:
            related_model = relation.related_model
            if related_model._meta.label in owned:
                continue
            # A join table Django made belongs to whichever model declared the
            # many-to-many field, and is the manifest's business only through that one.
            declared_by = getattr(related_model._meta, 'auto_created', False)
            if getattr(declared_by, '_meta', None) is not None and declared_by._meta.label in owned:
                continue
            field_name = relation.field.name
            try:
                pointing = related_model._base_manager.filter(
                    **{f'{field_name}__workspace': workspace}
                ).exists()
            except Exception:
                # A relation this cannot ask about is a relation this cannot clear, and
                # guessing would be guessing about a delete.
                logger.exception(
                    'Could not check whether %s still points at %s',
                    related_model._meta.label, model._meta.label,
                )
                pointing = True
            if pointing:
                raise ArchiveRefused(
                    'outside_references',
                    f'{related_model._meta.label} rows still point at {model._meta.label}, which is '
                    f'not a table this extension owns. Deleting would reach outside the archive.',
                    model=model._meta.label,
                    referenced_by=related_model._meta.label,
                )


def row_counts(workspace, models) -> Dict[str, int]:
    """How many rows of each table belong to ``workspace``. For a dry run."""
    return {
        model._meta.label: model._base_manager.filter(workspace=workspace).count()
        for model in models
    }


# ── Writing the archive ──────────────────────────────────────────────


def _applied_migrations() -> Dict[str, str]:
    """The last migration applied to each app, as the database has it.

    An app with no migrations, or a database with no migration table, answers an empty
    string — which compares equal to itself, so an unmigrated app does not block a restore.
    """
    latest: Dict[str, str] = {}
    for app_label, name in MigrationRecorder(connection).applied_migrations():
        if name > latest.get(app_label, ''):
            latest[app_label] = name
    return latest


def _digest(handle):
    """``(rows, checksum, bytes)`` of one export file, read a chunk at a time."""
    digest = hashlib.new(CHECKSUM_ALGORITHM)
    rows = 0
    size = 0
    last = b''
    while True:
        chunk = handle.read(CHUNK)
        if not chunk:
            break
        digest.update(chunk)
        rows += chunk.count(b'\n')
        size += len(chunk)
        last = chunk[-1:]
    if size and last != b'\n':
        # A file whose last line is unterminated still holds that row.
        rows += 1
    return rows, f'{CHECKSUM_ALGORITHM}:{digest.hexdigest()}', size


def _digest_file(path: str):
    with open(path, 'rb') as handle:
        return _digest(handle)


def _digest_stored(store, name: str):
    with store.open(name, 'rb') as handle:
        return _digest(handle)


def _save(store, name: str, handle) -> None:
    """Write one file, refusing a storage that put it somewhere else.

    Storage backends are allowed to rename what they are given rather than overwrite
    something — which would leave the archive holding a file the manifest does not name,
    and a restore looking for one that is not there.
    """
    saved = store.save(name, handle)
    if saved != name:
        raise ArchiveRefused(
            'storage_renamed_file',
            f'Storage wrote {saved!r} when asked for {name!r}; an archive whose files are not '
            f'where its manifest says cannot be restored.',
        )


def _export(store, workspace, record, models, now, previous) -> dict:
    """Write every table to storage and answer the manifest describing what was written."""
    directory = archive_directory(workspace.pk, record.key, now)
    if store.exists(posixpath.join(directory, MANIFEST_NAME)):
        raise ArchiveRefused(
            'archive_exists', f'{directory} already holds an archive; refusing to write over it.'
        )

    tables = []
    # Join rows are written inside the row that owns them rather than as a table of their
    # own, so they are counted as they go past: the delete is checked against this.
    joins: Counter = Counter(
        {field.remote_field.through._meta.label: 0 for model in models for field in _joined_through(model)}
    )
    with tempfile.TemporaryDirectory(prefix='bfg-extension-archive-') as workdir:
        for model in models:
            label = model._meta.label
            filename = f'{label}.jsonl'
            path = os.path.join(workdir, filename)
            with open(path, 'w', encoding='utf-8') as handle:
                serializers.serialize('jsonl', _rows_of(model, workspace, joins), stream=handle)
            rows, checksum, size = _digest_file(path)
            with open(path, 'rb') as handle:
                _save(store, posixpath.join(directory, filename), File(handle))
            tables.append(
                {'model': label, 'file': filename, 'rows': rows, 'checksum': checksum, 'bytes': size}
            )

    payload = {
        'format': FORMAT_VERSION,
        'extension': record.key,
        'workspace_id': workspace.pk,
        'workspace_slug': workspace.slug,
        'directory': directory,
        'archived_at': now.isoformat(),
        'status_before': previous['previous_status'],
        'status_reason_before': previous['previous_reason'],
        'status_changed_at': previous['previous_status_changed_at'],
        'config': record.config,
        'migrations': _migrations_of(models),
        'tables': tables,
        'joins': dict(joins),
        'total_rows': sum(table['rows'] for table in tables),
    }
    _save(
        store,
        posixpath.join(directory, MANIFEST_NAME),
        ContentFile(json.dumps(payload, indent=2, sort_keys=True, default=str).encode('utf-8')),
    )
    return payload


def _joined_through(model):
    """The many-to-many fields of ``model`` whose join table Django made for it."""
    return [
        field
        for field in model._meta.many_to_many
        if field.remote_field.through is not None and field.remote_field.through._meta.auto_created
    ]


def _rows_of(model, workspace, joins: Counter):
    """This workspace's rows of ``model``, with their join rows fetched alongside.

    The prefetch is the point. Django's serializer reads a many-to-many field through the
    model's *default* manager, and the default manager of a tenant-scoped model is empty
    unless a workspace is bound to the thread — which it is not in a management command.
    Left to itself the serializer would write ``[]`` for every join, quietly, and the
    delete afterwards would take the join rows with it. Prefetching through the base
    manager fills the cache the serializer looks in first, so what is written is what is
    there — and counting what it finds, into ``joins``, is what lets the delete be checked
    against the archive down to the join row.
    """
    queryset = model._base_manager.filter(workspace=workspace).order_by('pk')
    joined = _joined_through(model)
    if not joined:
        yield from queryset.iterator()
        return
    prefetches = [
        Prefetch(field.name, queryset=field.remote_field.model._base_manager.all())
        for field in joined
    ]
    for row in queryset.prefetch_related(*prefetches).iterator(chunk_size=2000):
        for field in joined:
            joins[field.remote_field.through._meta.label] += len(
                row._prefetched_objects_cache[field.name]
            )
        yield row


def refuse_split_joins(workspace, models) -> None:
    """Refuse when a join row ties this workspace's row to another workspace's.

    A join table Django made has no workspace of its own: its rows go when the rows they
    join go. That is right as long as both ends belong to the same workspace, and
    malformed data if they do not — so rather than delete a join whose other end this
    archive does not hold, the whole thing stops.
    """
    for model in models:
        for field in _joined_through(model):
            target = field.remote_field.model
            if not any(
                candidate.name == 'workspace' and candidate.is_relation
                for candidate in target._meta.concrete_fields
            ):
                # The other end is not something a workspace owns, so no join can cross one.
                continue
            through = field.remote_field.through
            joins = through._base_manager.filter(
                **{f'{field.m2m_field_name()}__workspace': workspace}
            )
            if joins.exclude(**{f'{field.m2m_reverse_field_name()}__workspace': workspace}).exists():
                raise ArchiveRefused(
                    'cross_workspace_join',
                    f'{model._meta.label}.{field.name} joins rows of this workspace to '
                    f'{target._meta.label} rows of another one. Deleting would break a join the '
                    f'archive cannot hold.',
                    model=model._meta.label,
                    field=field.name,
                )


def _migrations_of(models) -> Dict[str, str]:
    applied = _applied_migrations()
    return {model._meta.app_label: applied.get(model._meta.app_label, '') for model in models}


def _verify(store, payload) -> None:
    """Read the whole archive back out of storage and refuse anything that differs.

    Every byte is read again from where it was written rather than from the copy that was
    just made: a write that never arrived, a truncated upload or a storage silently
    writing somewhere else is exactly what this has to catch, because the next step
    deletes the only other copy.
    """
    directory = payload['directory']
    for table in payload['tables']:
        name = posixpath.join(directory, table['file'])
        if not store.exists(name):
            raise ArchiveRefused('missing_file', f'{name} is not in storage after being written.')
        rows, checksum, size = _digest_stored(store, name)
        if (rows, checksum, size) != (table['rows'], table['checksum'], table['bytes']):
            raise ArchiveRefused(
                'checksum_mismatch',
                f'{name} reads back as {rows} rows / {size} bytes / {checksum}, and was written as '
                f'{table["rows"]} rows / {table["bytes"]} bytes / {table["checksum"]}.',
                model=table['model'],
            )

    name = posixpath.join(directory, MANIFEST_NAME)
    try:
        with store.open(name, 'rb') as handle:
            written = json.loads(handle.read().decode('utf-8'))
    except (OSError, ValueError) as error:
        raise ArchiveRefused('manifest_unreadable', f'{name} cannot be read back: {error}') from None
    if written != json.loads(json.dumps(payload, default=str)):
        raise ArchiveRefused('manifest_mismatch', f'{name} is not what was written to it.')


# ── Archiving ────────────────────────────────────────────────────────


def archive_after_days() -> int:
    # The deployment's tunable numbers live in bfg.platform, which is also where the
    # console that changes them lives; imported here so bfg.common does not depend on it.
    from bfg.platform.services.platform_variables import get_variable

    return get_variable('archive_after_days')


def due_records(now=None, *, workspace=None, key=None, ignore_age: bool = False):
    """The records a sweep would archive, oldest first.

    An extension is due once it has been ``inactive`` or ``paused`` for
    ``archive_after_days``, counted from the moment it became so. Extensions this
    deployment does not ship, and ones that own no tables, are left out: there is nothing
    to write for them and archiving one would only take away the record of how it was
    configured.
    """
    WorkspaceExtension = _extension_model()

    now = now or timezone.now()
    archivable = [
        manifest.key
        for manifest in registry.all_manifests()
        if manifest.is_activatable and manifest.data_models
    ]
    if key is not None:
        archivable = [candidate for candidate in archivable if candidate == key]
    records = WorkspaceExtension.all_objects.filter(
        key__in=archivable,
        status__in=(WorkspaceExtension.STATUS_INACTIVE, WorkspaceExtension.STATUS_PAUSED),
    )
    if workspace is not None:
        records = records.filter(workspace=workspace)
    if not ignore_age:
        records = records.filter(
            status_changed_at__lte=now - dt.timedelta(days=archive_after_days())
        )
    return records.select_related('workspace').order_by('status_changed_at', 'workspace_id', 'key')


def archive(workspace, key, *, user=None, now=None, ignore_age: bool = False):
    """Write ``key``'s data for ``workspace`` to storage, check it, and delete the rows.

    Answers the record, now ``archived``, with ``archive_location`` naming the directory
    the archive was written to. Raises ``ArchiveNotConfigured`` when the deployment has
    nowhere to write, and ``ArchiveRefused`` for everything else — in which case the
    record is back on the status it had, carrying the reason.

    ``ignore_age`` archives an extension that is switched off but has not been for long
    enough. It is for an operator archiving one deliberately; a sweep never passes it.
    """
    store = archive_storage()
    manifest = _manifest_of(key)
    models = archivable_models(manifest)
    refuse_outside_references(workspace, models)
    refuse_split_joins(workspace, models)

    now = now or timezone.now()
    record = _claim(workspace, key, now=now, user=user, ignore_age=ignore_age)
    previous = dict(record.archive_state)
    try:
        payload = _export(store, workspace, record, models, now, previous)
        _verify(store, payload)
        _delete_and_seal(workspace, record, models, payload, now=now)
    except Exception as error:
        _release(record, error, reason=REASON_ARCHIVE_FAILED)
        raise
    return record


@transaction.atomic
def _claim(workspace, key, *, now, user, ignore_age):
    """Take the record for archiving, or refuse. Nothing is exported until this commits."""
    WorkspaceExtension = _extension_model()

    record = (
        WorkspaceExtension.all_objects.select_for_update()
        .filter(workspace=workspace, key=key)
        .first()
    )
    if record is None:
        raise ArchiveRefused('not_used', f'This workspace has never used {key}.')
    archivable_statuses = (WorkspaceExtension.STATUS_INACTIVE, WorkspaceExtension.STATUS_PAUSED)
    if record.status not in archivable_statuses:
        raise ArchiveRefused(
            'not_archivable',
            f'{key} is {record.status}; only an extension that is switched off or paused is archived.',
            status=record.status,
        )
    if not ignore_age:
        deadline = now - dt.timedelta(days=archive_after_days())
        if record.status_changed_at > deadline:
            raise ArchiveRefused(
                'too_soon',
                f'{key} has been {record.status} since {record.status_changed_at:%Y-%m-%d}, which is '
                f'not yet {archive_after_days()} days.',
                status=record.status,
            )

    record.archive_state = {
        'previous_status': record.status,
        'previous_reason': record.status_reason,
        'previous_status_changed_at': record.status_changed_at.isoformat(),
        'started_at': now.isoformat(),
    }
    record.status = WorkspaceExtension.STATUS_ARCHIVING
    record.status_reason = REASON_ARCHIVING
    record.status_changed_at = now
    record.status_changed_by = _actor(user)
    record.save()
    transaction.on_commit(lambda: invalidate(workspace.id))
    return record


@transaction.atomic
def _delete_and_seal(workspace, record, models, payload, *, now):
    """Delete exactly what was exported and mark the extension archived, or neither.

    The delete is asked what it deleted and checked against the archive, table by table.
    Anything else — a row written since the export, a cascade into a table the manifest
    does not list — rolls the whole transaction back with the rows still there, because a
    row that was deleted without being exported is a row that is gone.
    """
    WorkspaceExtension = _extension_model()

    fresh = WorkspaceExtension.all_objects.select_for_update().get(pk=record.pk)
    if fresh.status != WorkspaceExtension.STATUS_ARCHIVING:
        raise ArchiveRefused(
            'status_changed',
            f'{record.key} is {fresh.status} rather than archiving; nothing was deleted.',
            status=fresh.status,
        )
    # Again, here, inside the transaction that deletes: the export takes as long as it
    # takes, and a row written in the meantime that points at what is about to go would
    # otherwise be emptied or deleted without anything noticing. What the delete reports
    # catches a cascade; this catches a column being set to null, which it does not.
    refuse_outside_references(workspace, models)

    deleted: Counter = Counter()
    for model in reversed(models):
        _, per_label = model._base_manager.filter(workspace=workspace).delete()
        deleted.update(per_label)

    exported = {table['model']: table['rows'] for table in payload['tables']}
    exported.update(payload.get('joins') or {})
    allowed = set(exported) | _through_labels(models)
    unexpected = sorted(label for label, count in deleted.items() if count and label not in allowed)
    if unexpected:
        raise ArchiveRefused(
            'deleted_outside_archive',
            f'Deleting {record.key} would have taken rows out of {", ".join(unexpected)}, which the '
            f'archive does not hold. Nothing was deleted.',
            models=unexpected,
        )
    for label, expected in sorted(exported.items()):
        if deleted.get(label, 0) != expected:
            raise ArchiveRefused(
                'row_count_changed',
                f'{label} held {expected} rows when they were exported and {deleted.get(label, 0)} '
                f'when they were deleted. Nothing was deleted.',
                model=label,
            )

    state = dict(fresh.archive_state or {})
    state.update({
        'finished_at': now.isoformat(),
        'location': payload['directory'],
        'rows': payload['total_rows'],
        'tables': len(payload['tables']),
        'error': '',
        'error_code': '',
        'failed_at': '',
    })
    fresh.status = WorkspaceExtension.STATUS_ARCHIVED
    fresh.status_reason = REASON_ARCHIVED
    fresh.status_changed_at = now
    fresh.archive_location = payload['directory']
    fresh.archive_state = state
    fresh.save()
    transaction.on_commit(lambda: invalidate(workspace.id))

    record.status = fresh.status
    record.status_reason = fresh.status_reason
    record.archive_location = fresh.archive_location
    record.archive_state = fresh.archive_state
    return fresh


def _release(record, error, *, reason):
    """Put a run that failed back on the status it interrupted, with the reason on it.

    Called from an ``except`` block, so it reports its own failure rather than raising
    over the one being handled — an extension left on ``archiving`` is put back by the
    next sweep, whereas an exception lost here would be lost for good.
    """
    WorkspaceExtension = _extension_model()

    going_back_to = {
        REASON_ARCHIVE_FAILED: WorkspaceExtension.STATUS_ARCHIVING,
        REASON_RESTORE_FAILED: WorkspaceExtension.STATUS_RESTORING,
    }[reason]
    try:
        with transaction.atomic():
            fresh = WorkspaceExtension.all_objects.select_for_update().get(pk=record.pk)
            if fresh.status != going_back_to:
                # Something else has already moved it; that status is the current one.
                return fresh
            state = dict(fresh.archive_state or {})
            state.update({
                'error': str(error)[:500],
                'error_code': getattr(error, 'code', error.__class__.__name__),
                'failed_at': timezone.now().isoformat(),
            })
            fresh.status = _status_before(fresh, reason)
            fresh.status_reason = reason
            fresh.status_changed_at = _moment_before(fresh, reason)
            fresh.archive_state = state
            fresh.save()
            transaction.on_commit(lambda: invalidate(fresh.workspace_id))
            record.status = fresh.status
            record.status_reason = fresh.status_reason
            record.archive_state = fresh.archive_state
            return fresh
    except Exception:
        logger.exception(
            'Could not put extension %s of workspace %s back after a failed run',
            record.key, record.workspace_id,
        )
        return record


def _status_before(record, reason):
    WorkspaceExtension = _extension_model()

    if reason in (REASON_RESTORE_FAILED, REASON_RESTORE_INTERRUPTED):
        return WorkspaceExtension.STATUS_ARCHIVED
    previous = (record.archive_state or {}).get('previous_status')
    if previous in (WorkspaceExtension.STATUS_INACTIVE, WorkspaceExtension.STATUS_PAUSED):
        return previous
    # Nothing recorded, or something that is not a status to go back to. Switched off is
    # the safe answer: the data is still there and nobody is using it.
    return WorkspaceExtension.STATUS_INACTIVE


def _moment_before(record, reason):
    """The ``status_changed_at`` to go back to.

    An archive that failed does not restart the clock: the extension has been switched off
    since it was switched off, and pretending otherwise would hide a failing archive for
    another ``archive_after_days`` rather than trying it again tomorrow.
    """
    if reason in (REASON_RESTORE_FAILED, REASON_RESTORE_INTERRUPTED):
        return timezone.now()
    stamp = (record.archive_state or {}).get('previous_status_changed_at')
    if not stamp:
        return timezone.now()
    parsed = _parse(stamp)
    return parsed or timezone.now()


def _parse(stamp: str):
    try:
        parsed = dt.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, dt.timezone.utc)
    return parsed


# ── Restoring ────────────────────────────────────────────────────────


def begin_restore(workspace, key, *, user=None):
    """Put ``key`` on ``restoring`` so that whoever asked can see it is happening.

    Split from the loading so that a deployment can answer the request at once and load
    in a worker; ``restore`` does both in one go for everything else. Entitlement is not
    asked about here: this hands a workspace back its own data, and whether the extension
    then runs is what availability answers — an extension nobody is entitled to comes
    back ``active`` and unavailable, which is also what lets a workspace restore first and
    buy afterwards.
    """
    WorkspaceExtension = _extension_model()

    archive_storage()
    _manifest_of(key)
    with transaction.atomic():
        record = (
            WorkspaceExtension.all_objects.select_for_update()
            .filter(workspace=workspace, key=key)
            .first()
        )
        if record is None:
            raise ArchiveRefused('not_used', f'This workspace has never used {key}.')
        if record.status != WorkspaceExtension.STATUS_ARCHIVED:
            raise ArchiveRefused(
                'not_archived',
                f'{key} is {record.status}; only an archived extension is restored.',
                status=record.status,
            )
        if not record.archive_location:
            raise ArchiveRefused(
                'no_archive_location',
                f'{key} is archived but the record does not say where to, so there is nothing to '
                f'restore from.',
            )
        record.status = WorkspaceExtension.STATUS_RESTORING
        record.status_reason = REASON_RESTORING
        record.status_changed_at = timezone.now()
        record.status_changed_by = _actor(user)
        record.save()
        transaction.on_commit(lambda: invalidate(workspace.id))
    return record


def finish_restore(workspace, key):
    """Load an archive back and switch the extension on. ``begin_restore`` comes first.

    A failure puts the record back on ``archived`` with the reason, and nothing has been
    written: the load is one transaction. Running it again after a failure, or after it
    worked, loads the same rows onto the same primary keys rather than a second copy.
    """
    WorkspaceExtension = _extension_model()

    store = archive_storage()
    manifest = _manifest_of(key)
    record = _record(workspace, key)
    if record.status != WorkspaceExtension.STATUS_RESTORING:
        raise ArchiveRefused(
            'not_restoring',
            f'{key} is {record.status} rather than restoring.',
            status=record.status,
        )

    try:
        payload = _read_manifest(store, record.archive_location)
        _check_archive(payload, workspace, key)
        models = archivable_models(manifest)
        _check_migrations(payload, manifest, models)
        tables = _read_tables(store, payload, manifest)
        _load(workspace, record, models, payload, tables)
    except Exception as error:
        _release(record, error, reason=REASON_RESTORE_FAILED)
        raise
    return record


def restore(workspace, key, *, user=None):
    """Restore ``key`` for ``workspace`` and switch it on, start to finish."""
    begin_restore(workspace, key, user=user)
    return finish_restore(workspace, key)


def _read_manifest(store, location: str) -> dict:
    name = posixpath.join(location, MANIFEST_NAME)
    if not store.exists(name):
        raise ArchiveRefused(
            'archive_missing',
            f'{name} is not in storage. The archive this extension was told to restore from is '
            f'not there.',
        )
    try:
        with store.open(name, 'rb') as handle:
            payload = json.loads(handle.read().decode('utf-8'))
    except (OSError, ValueError) as error:
        raise ArchiveRefused('manifest_unreadable', f'{name} cannot be read: {error}') from None
    if not isinstance(payload, dict):
        raise ArchiveRefused('manifest_unreadable', f'{name} does not hold an archive manifest.')
    payload.setdefault('directory', location)
    return payload


def _check_archive(payload, workspace, key) -> None:
    """Refuse an archive that is not this workspace's copy of this extension."""
    if payload.get('format') != FORMAT_VERSION:
        raise ArchiveRefused(
            'unsupported_format',
            f'The archive was written in format {payload.get("format")!r}, and this deployment '
            f'reads format {FORMAT_VERSION}.',
        )
    if payload.get('extension') != key:
        raise ArchiveRefused(
            'wrong_extension',
            f'The archive holds {payload.get("extension")!r}, not {key}.',
        )
    if payload.get('workspace_id') != workspace.pk:
        raise ArchiveRefused(
            'wrong_workspace',
            f'The archive belongs to workspace {payload.get("workspace_id")!r}, not to this one.',
        )


def _check_migrations(payload, manifest, models) -> None:
    """Refuse an archive written against a schema that has moved, without a converter.

    ``restore_converters`` on the manifest maps an app label to a callable the extension
    provides for exactly this: the tables of that app are handed to it before they are
    loaded. Without one the restore stops and says which app has moved and how far, which
    is something an administrator can be shown and an extension's author can act on —
    loading rows shaped for one schema into another is how an archive becomes corruption.
    """
    current = _applied_migrations()
    archived = payload.get('migrations') or {}
    converters = manifest.restore_converters or {}
    for app_label in sorted({model._meta.app_label for model in models}):
        was = archived.get(app_label, '')
        now = current.get(app_label, '')
        if was == now:
            continue
        if app_label not in converters:
            raise ArchiveRefused(
                'migrations_changed',
                f'{app_label} was at migration {was or "none"} when the archive was written and is '
                f'at {now or "none"} now. {manifest.key} offers no converter for it, so the archive '
                f'cannot be loaded.',
                app_label=app_label,
                archived_migration=was,
                current_migration=now,
            )


def _read_tables(store, payload, manifest) -> Dict[str, List[dict]]:
    """Every table of the archive, checked against the manifest and converted if need be."""
    directory = payload['directory']
    converters = manifest.restore_converters or {}
    tables: Dict[str, List[dict]] = {}
    for table in payload.get('tables') or []:
        label = table['model']
        name = posixpath.join(directory, table['file'])
        if not store.exists(name):
            raise ArchiveRefused('missing_file', f'{name} is named by the archive but is not in storage.')
        rows, checksum, size = _digest_stored(store, name)
        if (rows, checksum, size) != (table['rows'], table['checksum'], table['bytes']):
            raise ArchiveRefused(
                'checksum_mismatch',
                f'{name} is not what was archived: it reads as {rows} rows / {size} bytes, and the '
                f'manifest says {table["rows"]} rows / {table["bytes"]} bytes.',
                model=label,
            )
        records = _read_rows(store, name)
        app_label = label.split('.')[0]
        converter = converters.get(app_label)
        if converter is not None:
            records = _convert(converter, payload, label, records, manifest)
        tables[label] = records
    return tables


def _read_rows(store, name: str) -> List[dict]:
    rows = []
    with store.open(name, 'rb') as handle:
        for number, line in enumerate(handle.read().decode('utf-8').splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as error:
                raise ArchiveRefused(
                    'unreadable_row', f'{name} line {number} is not readable: {error}'
                ) from None
    return rows


def _convert(converter, payload, label, records, manifest) -> List[dict]:
    try:
        converted = converter(payload, label, records)
    except ValueError as error:
        raise ArchiveRefused(
            'converter_refused',
            f'{manifest.key} could not convert {label} from the archive: {error}',
            model=label,
        ) from None
    if not isinstance(converted, list):
        raise ArchiveRefused(
            'converter_refused',
            f"{manifest.key}'s converter answered {type(converted).__name__} for {label} rather than "
            f'a list of rows.',
            model=label,
        )
    return converted


@transaction.atomic
def _load(workspace, record, models, payload, tables) -> None:
    """Write every row back, or none of them, and switch the extension on.

    Rows carry the primary keys they had, which is what makes loading the same archive
    twice an update of the same rows rather than a second set of them. A primary key that
    now holds a row of another workspace stops the whole restore: overwriting it would
    take away data from a workspace that has nothing to do with this one.
    """
    WorkspaceExtension = _extension_model()

    fresh = WorkspaceExtension.all_objects.select_for_update().get(pk=record.pk)
    if fresh.status != WorkspaceExtension.STATUS_RESTORING:
        raise ArchiveRefused(
            'status_changed',
            f'{record.key} is {fresh.status} rather than restoring; nothing was loaded.',
            status=fresh.status,
        )

    loaded = 0
    with connection.constraint_checks_disabled():
        for model in models:
            rows = tables.get(model._meta.label, [])
            _refuse_foreign_rows(workspace, model, rows)
            for deserialized in serializers.deserialize('python', rows):
                deserialized.save()
            loaded += len(rows)

    state = dict(fresh.archive_state or {})
    state.update({
        'restored_at': timezone.now().isoformat(),
        'restored_rows': loaded,
        'restored_from': payload['directory'],
        'error': '',
        'error_code': '',
        'failed_at': '',
    })
    now = timezone.now()
    fresh.status = WorkspaceExtension.STATUS_ACTIVE
    fresh.status_reason = ''
    fresh.status_changed_at = now
    fresh.activated_at = now
    fresh.archive_state = state
    fresh.save()
    transaction.on_commit(lambda: invalidate(workspace.id))

    record.status = fresh.status
    record.status_reason = fresh.status_reason
    record.archive_state = fresh.archive_state


def _refuse_foreign_rows(workspace, model, rows) -> None:
    """Refuse rows that are not this workspace's, and primary keys that are somebody else's."""
    label = model._meta.label
    keys = []
    for row in rows:
        if str(row.get('model', '')).lower() != label.lower():
            raise ArchiveRefused(
                'wrong_table',
                f'A row in the archive says it is {row.get("model")!r} while it is being loaded as '
                f'{label}.',
                model=label,
            )
        fields = row.get('fields') or {}
        if fields.get('workspace') != workspace.pk:
            raise ArchiveRefused(
                'foreign_rows',
                f'A {label} row in the archive belongs to workspace {fields.get("workspace")!r} '
                f'rather than to this one.',
                model=label,
            )
        keys.append(row.get('pk'))

    if not keys:
        return
    taken = (
        model._base_manager.filter(pk__in=keys)
        .exclude(workspace=workspace)
        .values_list('pk', flat=True)[:5]
    )
    taken = list(taken)
    if taken:
        raise ArchiveRefused(
            'key_conflict',
            f'{label} rows {taken} now belong to another workspace, so the archive cannot be '
            f'loaded onto them.',
            model=label,
        )


# ── Sweeping ─────────────────────────────────────────────────────────


def stuck_minutes() -> int:
    try:
        return max(1, int(getattr(settings, 'BFG_EXTENSION_ARCHIVE_STUCK_MINUTES', DEFAULT_STUCK_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_STUCK_MINUTES


def release_stuck(now=None) -> List[dict]:
    """Put back anything left mid-run by a process that died.

    A run holds no lock between its steps — it cannot, because exporting takes as long as
    it takes — so a worker killed halfway leaves ``archiving`` or ``restoring`` behind and
    nothing else would ever move it. Anything older than ``stuck_minutes`` goes back:
    ``archiving`` to the status it interrupted, with the rows still there because they are
    only ever deleted in the same transaction that writes ``archived``; ``restoring`` to
    ``archived``, because the load is one transaction as well.

    Releasing one that is in fact still running is harmless: both transactions check that
    the status is still theirs before writing anything, and the run that finds it is not
    fails and changes nothing.
    """
    WorkspaceExtension = _extension_model()

    now = now or timezone.now()
    cutoff = now - dt.timedelta(minutes=stuck_minutes())
    released = []
    stuck = WorkspaceExtension.all_objects.filter(
        status__in=(WorkspaceExtension.STATUS_ARCHIVING, WorkspaceExtension.STATUS_RESTORING),
        status_changed_at__lte=cutoff,
    ).order_by('workspace_id', 'key')
    for record in stuck:
        reason = (
            REASON_ARCHIVE_INTERRUPTED
            if record.status == WorkspaceExtension.STATUS_ARCHIVING
            else REASON_RESTORE_INTERRUPTED
        )
        was = record.status
        with transaction.atomic():
            fresh = WorkspaceExtension.all_objects.select_for_update().get(pk=record.pk)
            if fresh.status != was:
                continue
            state = dict(fresh.archive_state or {})
            state.update({
                'error': f'Interrupted while {was}; put back by the sweep.',
                'error_code': reason,
                'failed_at': now.isoformat(),
            })
            fresh.status = _status_before(fresh, reason)
            fresh.status_reason = reason
            fresh.status_changed_at = _moment_before(fresh, reason)
            fresh.archive_state = state
            fresh.save()
            transaction.on_commit(lambda workspace_id=fresh.workspace_id: invalidate(workspace_id))
        released.append({
            'workspace_id': record.workspace_id,
            'key': record.key,
            'was': was,
            'status': fresh.status,
            'reason': reason,
        })
    return released


def sweep(
    *,
    now=None,
    workspace=None,
    key: Optional[str] = None,
    limit: Optional[int] = None,
    ignore_age: bool = False,
    dry_run: bool = False,
) -> dict:
    """Archive everything that is due, and answer what happened to each.

    Raises ``ArchiveNotConfigured`` before looking at anything when the deployment has
    nowhere to write. A dry run reads only: it runs the same checks and counts the rows
    each archive would hold, and writes, deletes and releases nothing.

    Safe to run as often as one likes: an extension archived by the last run is no longer
    due, and one refused by it is refused again with the same reason.
    """
    archive_storage()
    now = now or timezone.now()
    released = [] if dry_run else release_stuck(now)

    archived, refused = [], []
    records = due_records(now, workspace=workspace, key=key, ignore_age=ignore_age)
    if limit:
        records = records[:limit]
    for record in list(records):
        entry = {'workspace_id': record.workspace_id, 'key': record.key, 'status': record.status}
        try:
            if dry_run:
                manifest = _manifest_of(record.key)
                models = archivable_models(manifest)
                refuse_outside_references(record.workspace, models)
                refuse_split_joins(record.workspace, models)
                counts = row_counts(record.workspace, models)
                archived.append({**entry, 'rows': sum(counts.values()), 'tables': len(counts)})
            else:
                done = archive(record.workspace, record.key, now=now, ignore_age=ignore_age)
                state = done.archive_state or {}
                archived.append({
                    **entry,
                    'location': done.archive_location,
                    'rows': state.get('rows', 0),
                    'tables': state.get('tables', 0),
                })
        except ExtensionError as error:
            refused.append({**entry, 'code': error.code, 'detail': error.message})
        except Exception as error:  # noqa: BLE001 - one extension must not stop the sweep
            logger.exception(
                'Archiving extension %s of workspace %s failed', record.key, record.workspace_id
            )
            refused.append({**entry, 'code': 'error', 'detail': str(error)})
    return {'archived': archived, 'refused': refused, 'released': released, 'dry_run': dry_run}

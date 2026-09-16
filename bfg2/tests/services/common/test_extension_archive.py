"""Archiving the data of an extension nobody uses any more, and loading it back.

The tables belong to ``tests.extension_data``, a test-only app shaped like the ones an
extension owns, and the manifest declaring them is faked the same way the rest of the
extension suite fakes manifests — so none of this depends on which extensions a
deployment installs. Archives are written to a directory under ``tmp_path``, which is
storage of its own as far as the code is concerned.

Read the assertions about what is *not* deleted as the point of the file: this is the
one place in the library that deletes a workspace's rows.
"""

import datetime as dt
import json
from io import StringIO

import pytest
from django.conf import settings as django_settings
from django.core.files.base import ContentFile
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from bfg.common.extensions import archive, registry, services
from bfg.common.extensions.archive_storage import ArchiveNotConfigured
from bfg.common.extensions.manifest import ExtensionManifest
from bfg.common.models import StaffMember, StaffRole, User, Workspace, WorkspaceExtension
from bfg.platform.models.variables import PlatformVariable
from bfg.platform.services.ownership import assign_workspace_owner
from tests.extension_data.models import ArchiveComment, ArchiveMention, ArchiveNote, ArchiveTag

NOTES = 'extension_data_tests.ArchiveNote'
COMMENTS = 'extension_data_tests.ArchiveComment'
TAGS = 'extension_data_tests.ArchiveTag'
MENTIONS = 'extension_data_tests.ArchiveMention'

OWNED = (TAGS, NOTES, COMMENTS)


def _manifests(**overrides):
    notes = ExtensionManifest(
        key='notes',
        name='Notes',
        app_label='extension_data_tests',
        **{'data_models': OWNED, **overrides},
    )
    return {
        'notes': notes,
        # Something deployed that owns no tables, so the sweep has a record to skip.
        'plain': ExtensionManifest(key='plain', name='Plain', app_label='plain_app'),
    }


@pytest.fixture(autouse=True)
def fake_manifests(monkeypatch):
    monkeypatch.setattr(registry, '_discover', _manifests)
    registry.reset_cache()
    services._load_entitlement_check.cache_clear()
    cache.clear()
    yield
    registry.reset_cache()
    services._load_entitlement_check.cache_clear()
    cache.clear()


@pytest.fixture
def store(settings, tmp_path):
    """Archiving configured, writing to a directory of its own."""
    settings.STORAGES = {
        **django_settings.STORAGES,
        'extension_archive': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
            'OPTIONS': {'location': str(tmp_path / 'archives')},
        },
    }
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = 'extension_archive'
    settings.BFG_EXTENSION_ARCHIVE_PREFIX = 'archives'
    return archive.archive_storage()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Archive WS', slug='archive-ws', is_active=True)


@pytest.fixture
def neighbour(db):
    return Workspace.objects.create(name='Neighbour WS', slug='neighbour-ws', is_active=True)


def _fill(workspace, *, titles=('first', 'second')):
    """Two notes with a comment and a tag apiece, so every table has rows."""
    tag = ArchiveTag.all_objects.create(workspace=workspace, label=f'{workspace.slug}-tag')
    notes = []
    for title in titles:
        note = ArchiveNote.all_objects.create(workspace=workspace, title=title, body=f'{title} body')
        note.tags.add(tag)
        ArchiveComment.all_objects.create(workspace=workspace, note=note, body=f'on {title}')
        notes.append(note)
    return notes


def _switched_off(workspace, *, days_ago=40, status=WorkspaceExtension.STATUS_INACTIVE, key='notes'):
    return WorkspaceExtension.all_objects.create(
        workspace=workspace,
        key=key,
        status=status,
        status_reason='deactivated',
        status_changed_at=timezone.now() - dt.timedelta(days=days_ago),
    )


def _rows(workspace):
    return (
        ArchiveTag.all_objects.filter(workspace=workspace).count(),
        ArchiveNote.all_objects.filter(workspace=workspace).count(),
        ArchiveComment.all_objects.filter(workspace=workspace).count(),
    )


def _read(store, location, name):
    with store.open(f'{location}/{name}', 'rb') as handle:
        return handle.read().decode('utf-8')


def _manifest_json(store, location):
    return json.loads(_read(store, location, archive.MANIFEST_NAME))


# ── Nothing without somewhere to write ───────────────────────────────


def test_archiving_is_off_until_a_storage_is_named(workspace, settings):
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = ''
    record = _switched_off(workspace)
    _fill(workspace)

    assert archive.is_configured() is False
    assert 'BFG_EXTENSION_ARCHIVE_STORAGE' in archive.why_unconfigured()
    with pytest.raises(ArchiveNotConfigured):
        archive.sweep()
    with pytest.raises(ArchiveNotConfigured):
        archive.archive(workspace, 'notes')

    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 2, 2)


@pytest.mark.parametrize('alias', ['default', 'staticfiles'])
def test_the_storage_that_is_served_is_refused(workspace, settings, alias):
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = alias

    assert archive.is_configured() is False
    assert 'serves' in archive.why_unconfigured()


def test_a_storage_inside_the_media_directory_is_refused(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    settings.STORAGES = {
        **django_settings.STORAGES,
        'extension_archive': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
            'OPTIONS': {'location': str(tmp_path / 'media' / 'archives')},
        },
    }
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = 'extension_archive'

    assert archive.is_configured() is False
    assert 'MEDIA_ROOT' in archive.why_unconfigured()


class CdnStorage:
    """A storage the deployment put behind a CDN, which is what makes it public."""

    custom_domain = 'files.example.test'


class BucketStorage:
    """An object store, standing in for the S3 backend a deployment configures."""

    bucket_name = 'the-one-that-is-served'
    custom_domain = None


def test_the_bucket_the_deployment_serves_is_refused_even_under_its_own_prefix(settings):
    settings.STORAGES = {
        'default': {'BACKEND': f'{__name__}.BucketStorage'},
        'staticfiles': django_settings.STORAGES['staticfiles'],
        'extension_archive': {'BACKEND': f'{__name__}.BucketStorage'},
    }
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = 'extension_archive'
    settings.BFG_EXTENSION_ARCHIVE_PREFIX = 'somewhere-else'

    assert archive.is_configured() is False
    assert 'bucket this deployment serves media from' in archive.why_unconfigured()


def test_a_storage_behind_a_cdn_is_refused(settings):
    settings.STORAGES = {
        **django_settings.STORAGES,
        'extension_archive': {'BACKEND': f'{__name__}.CdnStorage'},
    }
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = 'extension_archive'

    assert archive.is_configured() is False
    assert 'custom_domain' in archive.why_unconfigured()


# ── When an extension is due ─────────────────────────────────────────


def test_an_extension_switched_off_recently_is_not_archived(workspace, store):
    record = _switched_off(workspace, days_ago=5)
    _fill(workspace)

    report = archive.sweep()

    assert report['archived'] == []
    record.refresh_from_db()
    assert (record.status, record.archive_location) == (WorkspaceExtension.STATUS_INACTIVE, '')
    assert _rows(workspace) == (1, 2, 2)


def test_asking_for_one_that_is_not_due_says_how_long_it_has_been(workspace, store):
    _switched_off(workspace, days_ago=5)
    _fill(workspace)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'too_soon'
    assert _rows(workspace) == (1, 2, 2)


def test_the_days_to_wait_are_a_platform_variable(workspace, store):
    PlatformVariable.objects.create(key='archive_after_days', value=3)
    cache.clear()
    _switched_off(workspace, days_ago=5)
    _fill(workspace)

    report = archive.sweep()

    assert [entry['key'] for entry in report['archived']] == ['notes']


@pytest.mark.parametrize(
    'status', [WorkspaceExtension.STATUS_INACTIVE, WorkspaceExtension.STATUS_PAUSED]
)
def test_an_extension_off_for_long_enough_is_archived(workspace, neighbour, store, status):
    record = _switched_off(workspace, status=status)
    _fill(workspace)
    _fill(neighbour, titles=('theirs',))

    report = archive.sweep()

    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED
    assert record.status_reason == archive.REASON_ARCHIVED
    assert record.archive_location.startswith(f'archives/workspace-{workspace.pk}/notes/')
    assert report['archived'][0]['rows'] == 5

    # The workspace's rows are gone and the workspace next door has not lost one.
    assert _rows(workspace) == (0, 0, 0)
    assert _rows(neighbour) == (1, 1, 1)


def test_the_archive_holds_a_file_per_table_and_a_manifest(workspace, store):
    _switched_off(workspace)
    _fill(workspace)

    archive.archive(workspace, 'notes')

    record = WorkspaceExtension.all_objects.get(workspace=workspace, key='notes')
    payload = _manifest_json(store, record.archive_location)
    assert payload['format'] == archive.FORMAT_VERSION
    assert (payload['extension'], payload['workspace_id']) == ('notes', workspace.pk)
    assert payload['status_before'] == WorkspaceExtension.STATUS_INACTIVE
    assert payload['total_rows'] == 5
    assert [table['model'] for table in payload['tables']] == list(OWNED)
    assert payload['migrations'] == {'extension_data_tests': ''}
    for table in payload['tables']:
        assert table['checksum'].startswith('sha256:')
        lines = [line for line in _read(store, record.archive_location, table['file']).splitlines() if line]
        assert len(lines) == table['rows']
        assert {json.loads(line)['fields']['workspace'] for line in lines} == {workspace.pk}


def test_only_the_workspace_being_archived_is_written_to_the_archive(workspace, neighbour, store):
    _switched_off(workspace)
    _fill(workspace)
    _fill(neighbour, titles=('theirs', 'also theirs'))

    record = archive.archive(workspace, 'notes')

    payload = _manifest_json(store, record.archive_location)
    titles = {
        json.loads(line)['fields']['title']
        for table in payload['tables']
        if table['model'] == NOTES
        for line in _read(store, record.archive_location, table['file']).splitlines()
        if line
    }
    assert titles == {'first', 'second'}


def test_an_extension_that_owns_no_tables_is_left_alone(workspace, store):
    record = _switched_off(workspace, key='plain')

    report = archive.sweep()

    assert report['archived'] == [] and report['refused'] == []
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE


def test_the_rows_that_join_two_tables_are_written_to_the_archive(workspace, store):
    """The joins are the easiest thing to lose: nothing holds them but the join table.

    Django's serializer reads a many-to-many field through the model's default manager,
    which for a tenant-scoped model answers nothing at all outside a request — so this
    asserts on what was written rather than only on what comes back.
    """
    _switched_off(workspace)
    notes = _fill(workspace)
    tag = ArchiveTag.all_objects.get(workspace=workspace)

    record = archive.archive(workspace, 'notes')

    payload = _manifest_json(store, record.archive_location)
    table = next(entry for entry in payload['tables'] if entry['model'] == NOTES)
    written = [json.loads(line) for line in _read(store, record.archive_location, table['file']).splitlines() if line]
    assert sorted(row['pk'] for row in written) == sorted(note.pk for note in notes)
    assert all(row['fields']['tags'] == [tag.pk] for row in written)


def test_a_join_that_crosses_workspaces_stops_the_archive(workspace, neighbour, store):
    record = _switched_off(workspace)
    notes = _fill(workspace)
    theirs = ArchiveTag.all_objects.create(workspace=neighbour, label='theirs')
    notes[0].tags.add(theirs)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'cross_workspace_join'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 2, 2)


# ── What it refuses to delete ────────────────────────────────────────


def test_a_table_with_no_workspace_column_is_refused(workspace, store, monkeypatch):
    monkeypatch.setattr(registry, '_discover', lambda: _manifests(data_models=(NOTES, MENTIONS)))
    registry.reset_cache()
    record = _switched_off(workspace)
    _fill(workspace)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'unscoped_model'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 2, 2)


def test_rows_outside_the_manifest_pointing_in_stop_the_archive(workspace, store):
    record = _switched_off(workspace)
    notes = _fill(workspace)
    ArchiveMention.objects.create(note=notes[0], note_text='someone else cares about this')

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'outside_references'
    assert MENTIONS in refusal.value.details['referenced_by']
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 2, 2)
    assert ArchiveMention.objects.count() == 1


def test_an_export_that_does_not_read_back_leaves_every_row_where_it_was(workspace, store, monkeypatch):
    record = _switched_off(workspace)
    _fill(workspace)

    def corrupt(store_, payload):
        raise archive.ArchiveRefused('checksum_mismatch', 'the archive reads back short.')

    monkeypatch.setattr(archive, '_verify', corrupt)

    with pytest.raises(archive.ArchiveRefused):
        archive.archive(workspace, 'notes')

    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert record.status_reason == archive.REASON_ARCHIVE_FAILED
    assert record.archive_state['error_code'] == 'checksum_mismatch'
    assert 'reads back short' in record.archive_state['error']
    assert _rows(workspace) == (1, 2, 2)


def test_a_truncated_file_in_storage_is_caught_before_anything_is_deleted(workspace, store, monkeypatch):
    record = _switched_off(workspace)
    _fill(workspace)
    real_export = archive._export

    def export_then_truncate(store_, workspace_, record_, models, now, previous):
        payload = real_export(store_, workspace_, record_, models, now, previous)
        name = f'{payload["directory"]}/{payload["tables"][0]["file"]}'
        store_.delete(name)
        store_.save(name, ContentFile(b''))
        return payload

    monkeypatch.setattr(archive, '_export', export_then_truncate)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'checksum_mismatch'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 2, 2)


def test_a_row_written_between_the_export_and_the_delete_rolls_the_delete_back(
    workspace, store, monkeypatch
):
    record = _switched_off(workspace)
    _fill(workspace)
    real_verify = archive._verify

    def verify_then_write(store_, payload):
        real_verify(store_, payload)
        ArchiveNote.all_objects.create(workspace=workspace, title='snuck in')

    monkeypatch.setattr(archive, '_verify', verify_then_write)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'row_count_changed'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 3, 2)


def test_a_join_added_between_the_export_and_the_delete_rolls_the_delete_back(
    workspace, store, monkeypatch
):
    record = _switched_off(workspace)
    notes = _fill(workspace)
    spare = ArchiveTag.all_objects.create(workspace=workspace, label='spare')
    real_verify = archive._verify

    def verify_then_join(store_, payload):
        real_verify(store_, payload)
        notes[0].tags.add(spare)

    monkeypatch.setattr(archive, '_verify', verify_then_join)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.archive(workspace, 'notes')

    assert refusal.value.code == 'row_count_changed'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert ArchiveTag.all_objects.filter(notes=notes[0]).count() == 2


def test_the_failure_shows_up_on_the_record_rather_than_leaving_it_archiving(
    workspace, store, monkeypatch
):
    record = _switched_off(workspace, status=WorkspaceExtension.STATUS_PAUSED)
    _fill(workspace)
    monkeypatch.setattr(
        archive, '_export', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('storage is down'))
    )

    with pytest.raises(OSError):
        archive.archive(workspace, 'notes')

    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_PAUSED
    assert record.status_reason == archive.REASON_ARCHIVE_FAILED
    assert record.archive_state['error_code'] == 'OSError'
    # The clock is not restarted: tomorrow's sweep tries it again rather than in a month.
    assert record.status_changed_at < timezone.now() - dt.timedelta(days=39)


def test_an_interrupted_run_is_put_back_by_the_next_sweep(workspace, store, settings):
    settings.BFG_EXTENSION_ARCHIVE_STUCK_MINUTES = 30
    record = _switched_off(workspace)
    record.status = WorkspaceExtension.STATUS_ARCHIVING
    record.status_reason = archive.REASON_ARCHIVING
    record.status_changed_at = timezone.now() - dt.timedelta(hours=3)
    record.archive_state = {
        'previous_status': WorkspaceExtension.STATUS_INACTIVE,
        'previous_status_changed_at': (timezone.now() - dt.timedelta(days=40)).isoformat(),
    }
    record.save()
    _fill(workspace)

    report = archive.sweep()

    record.refresh_from_db()
    assert report['released'][0]['was'] == WorkspaceExtension.STATUS_ARCHIVING
    # Put back, and due again, so the same run archives it properly.
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED
    assert _rows(workspace) == (0, 0, 0)


def test_a_restore_interrupted_goes_back_to_archived(workspace, store, settings):
    settings.BFG_EXTENSION_ARCHIVE_STUCK_MINUTES = 30
    record = _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')
    record.refresh_from_db()
    record.status = WorkspaceExtension.STATUS_RESTORING
    record.status_changed_at = timezone.now() - dt.timedelta(hours=3)
    record.save()

    released = archive.release_stuck()

    record.refresh_from_db()
    assert released[0]['reason'] == archive.REASON_RESTORE_INTERRUPTED
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED


# ── Coming back ──────────────────────────────────────────────────────


def test_restoring_brings_every_row_back_and_switches_the_extension_on(workspace, neighbour, store):
    record = _switched_off(workspace)
    notes = _fill(workspace)
    _fill(neighbour, titles=('theirs',))
    keys = sorted(note.pk for note in notes)
    archive.archive(workspace, 'notes')
    assert _rows(workspace) == (0, 0, 0)

    restored = archive.restore(workspace, 'notes')

    assert restored.status == WorkspaceExtension.STATUS_ACTIVE
    assert restored.status_reason == ''
    assert _rows(workspace) == (1, 2, 2)
    assert sorted(ArchiveNote.all_objects.filter(workspace=workspace).values_list('pk', flat=True)) == keys
    note = ArchiveNote.all_objects.get(workspace=workspace, title='first')
    # Through ``all_objects``: a related manager reads the tenant-scoped one, which is
    # empty outside a request.
    assert ArchiveComment.all_objects.filter(note=note).count() == 1
    assert ArchiveTag.all_objects.filter(notes=note).count() == 1
    assert _rows(neighbour) == (1, 1, 1)
    record.refresh_from_db()
    assert record.archive_state['restored_rows'] == 5


def test_restoring_the_same_archive_twice_writes_the_same_rows(workspace, store):
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')
    archive.restore(workspace, 'notes')

    # A second restore of the same archive: the extension is active again, so it is
    # switched off first, exactly as a person clicking restore twice would leave it.
    record = WorkspaceExtension.all_objects.get(workspace=workspace, key='notes')
    record.status = WorkspaceExtension.STATUS_ARCHIVED
    record.save()
    archive.restore(workspace, 'notes')

    assert _rows(workspace) == (1, 2, 2)
    assert ArchiveNote.all_objects.filter(workspace=workspace).count() == 2


def test_an_archive_written_against_another_schema_is_refused(workspace, store):
    _switched_off(workspace)
    _fill(workspace)
    record = archive.archive(workspace, 'notes')
    _rewrite_manifest(store, record.archive_location, migrations={'extension_data_tests': '0009_later'})

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.restore(workspace, 'notes')

    assert refusal.value.code == 'migrations_changed'
    assert refusal.value.details['archived_migration'] == '0009_later'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED
    assert record.status_reason == archive.REASON_RESTORE_FAILED
    assert 'no converter' in record.archive_state['error']
    assert _rows(workspace) == (0, 0, 0)


def test_a_converter_lets_an_older_archive_be_loaded(workspace, store, monkeypatch):
    _switched_off(workspace)
    _fill(workspace)
    record = archive.archive(workspace, 'notes')
    _rewrite_manifest(store, record.archive_location, migrations={'extension_data_tests': '0009_later'})

    def convert(payload, label, rows):
        if label != NOTES:
            return rows
        for row in rows:
            row['fields']['title'] = f'converted {row["fields"]["title"]}'
        return rows

    monkeypatch.setattr(
        registry, '_discover', lambda: _manifests(restore_converters={'extension_data_tests': convert})
    )
    registry.reset_cache()

    archive.restore(workspace, 'notes')

    assert set(ArchiveNote.all_objects.filter(workspace=workspace).values_list('title', flat=True)) == {
        'converted first', 'converted second'
    }


def test_a_converter_that_refuses_leaves_the_extension_archived(workspace, store, monkeypatch):
    _switched_off(workspace)
    _fill(workspace)
    record = archive.archive(workspace, 'notes')
    _rewrite_manifest(store, record.archive_location, migrations={'extension_data_tests': '0009_later'})

    def refuse(payload, label, rows):
        raise ValueError('the rating column cannot be worked out from what was archived')

    monkeypatch.setattr(
        registry, '_discover', lambda: _manifests(restore_converters={'extension_data_tests': refuse})
    )
    registry.reset_cache()

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.restore(workspace, 'notes')

    assert refusal.value.code == 'converter_refused'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED
    assert _rows(workspace) == (0, 0, 0)


def test_a_primary_key_another_workspace_now_holds_stops_the_restore(workspace, neighbour, store):
    _switched_off(workspace)
    notes = _fill(workspace)
    record = archive.archive(workspace, 'notes')

    # The neighbour's shop has since been given the primary key this archive holds.
    ArchiveNote.all_objects.create(pk=notes[0].pk, workspace=neighbour, title='theirs now')

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.restore(workspace, 'notes')

    assert refusal.value.code == 'key_conflict'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED
    assert ArchiveNote.all_objects.get(pk=notes[0].pk).title == 'theirs now'
    assert _rows(workspace) == (0, 0, 0)


def test_an_archive_belonging_to_another_workspace_is_refused(workspace, neighbour, store):
    _switched_off(workspace)
    _fill(workspace)
    record = archive.archive(workspace, 'notes')
    _rewrite_manifest(store, record.archive_location, workspace_id=neighbour.pk)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.restore(workspace, 'notes')

    assert refusal.value.code == 'wrong_workspace'


def test_an_archive_that_is_no_longer_in_storage_is_refused(workspace, store):
    _switched_off(workspace)
    _fill(workspace)
    record = archive.archive(workspace, 'notes')
    store.delete(f'{record.archive_location}/{archive.MANIFEST_NAME}')

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.restore(workspace, 'notes')

    assert refusal.value.code == 'archive_missing'
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_ARCHIVED


def test_only_an_archived_extension_is_restored(workspace, store):
    _switched_off(workspace)

    with pytest.raises(archive.ArchiveRefused) as refusal:
        archive.restore(workspace, 'notes')

    assert refusal.value.code == 'not_archived'


def test_an_archived_extension_is_not_activated_but_restored(workspace, store):
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')

    with pytest.raises(services.ExtensionError) as refusal:
        services.activate(workspace, 'notes')

    assert refusal.value.code == 'archived'
    assert 'restore' in refusal.value.message


def test_applying_a_plan_pack_leaves_an_archived_extension_alone(workspace, store, settings):
    """A pack switches things on, and an archived extension is not something to switch on.

    It is skipped with the reason, and the rest of the pack still applies — the alternative
    would be a pack that half-activates an extension whose rows are not in the database.
    """
    from bfg.common.extensions import packs

    settings.BFG_EXTENSION_PLAN_PACKS = {'shop': {'name': 'Shop', 'extensions': ('notes',)}}
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')

    applied = packs.apply_pack(workspace, 'shop')

    assert applied == [
        {'key': 'notes', 'outcome': packs.OUTCOME_SKIPPED, 'code': 'archived',
         'detail': "notes's data was archived; restore it before activating."}
    ]
    assert WorkspaceExtension.all_objects.get(workspace=workspace, key='notes').status == (
        WorkspaceExtension.STATUS_ARCHIVED
    )


def entitled_to_nothing(workspace, manifest):
    return False


def test_a_workspace_gets_its_data_back_before_it_is_entitled_again(workspace, store, settings):
    """Restoring is not a purchase, so it does not ask whether the workspace may buy.

    An add-on that lapsed, was archived and is being bought again has to be restorable
    first: activation is what an entitlement gates, and activating an archived extension is
    refused, so requiring one here would leave the workspace unable to do either. The
    extension comes back active and unavailable, which is what availability is for.
    """
    settings.BFG_EXTENSION_ENTITLEMENT_CHECK = f'{__name__}.entitled_to_nothing'
    services._load_entitlement_check.cache_clear()
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')

    restored = archive.restore(workspace, 'notes')

    assert restored.status == WorkspaceExtension.STATUS_ACTIVE
    assert _rows(workspace) == (1, 2, 2)
    assert 'notes' not in services.compute_available_keys(workspace)


def _rewrite_manifest(store, location, **changes):
    name = f'{location}/{archive.MANIFEST_NAME}'
    payload = _manifest_json(store, location)
    payload.update(changes)
    store.delete(name)
    store.save(name, ContentFile(json.dumps(payload).encode('utf-8')))


# ── The command ──────────────────────────────────────────────────────


def _run(*args, **options):
    out, err = StringIO(), StringIO()
    call_command('archive_unused_extensions', *args, stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def test_the_command_says_so_and_stops_when_there_is_nowhere_to_write(workspace, settings):
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = ''
    _switched_off(workspace)
    _fill(workspace)

    with pytest.raises(CommandError) as refusal:
        _run()

    assert 'BFG_EXTENSION_ARCHIVE_STORAGE' in str(refusal.value)
    assert _rows(workspace) == (1, 2, 2)


def test_a_dry_run_writes_nothing_and_deletes_nothing(workspace, store):
    record = _switched_off(workspace)
    _fill(workspace)

    out, _ = _run('--dry-run')

    assert 'would archive' in out and '5 rows' in out
    record.refresh_from_db()
    assert record.status == WorkspaceExtension.STATUS_INACTIVE
    assert _rows(workspace) == (1, 2, 2)
    assert not store.exists('archives')


def test_the_command_archives_what_is_due_and_says_where_it_went(workspace, store):
    _switched_off(workspace)
    _fill(workspace)

    out, _ = _run()

    assert 'archived' in out and 'archives/workspace-' in out
    assert _rows(workspace) == (0, 0, 0)


def test_the_command_reports_a_refusal_without_failing_the_rest(workspace, neighbour, store):
    _switched_off(workspace)
    _switched_off(neighbour)
    notes = _fill(workspace)
    _fill(neighbour)
    ArchiveMention.objects.create(note=notes[0], note_text='in the way')

    out, err = _run()

    assert 'outside_references' in err
    assert _rows(workspace) == (1, 2, 2)
    assert _rows(neighbour) == (0, 0, 0)
    assert '1 extensions archived, 1 refused' in out


def test_the_command_can_archive_one_extension_before_it_is_due(workspace, store):
    _switched_off(workspace, days_ago=1)
    _fill(workspace)

    with pytest.raises(CommandError):
        _run('--ignore-age')

    _run('--workspace', workspace.slug, '--key', 'notes', '--ignore-age')

    assert _rows(workspace) == (0, 0, 0)


def test_the_extensions_command_restores_one(workspace, store):
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')

    out = StringIO()
    call_command('workspace_extensions', 'restore', 'notes', '--workspace', workspace.slug, stdout=out)

    assert 'active' in out.getvalue()
    assert _rows(workspace) == (1, 2, 2)


# ── The console ──────────────────────────────────────────────────────


@pytest.fixture
def owner(workspace, settings):
    settings.PLATFORM_EMBEDDED = True
    settings.PLATFORM_WORKSPACE_SLUG = 'platform'
    Workspace.objects.get_or_create(slug='platform', defaults={'name': 'Platform', 'is_active': True})
    role, _ = StaffRole.objects.get_or_create(
        workspace=workspace, code='owner', defaults={'name': 'Owner'}
    )
    user = User.objects.create_user(username='console', email='console@example.com', password='x')
    StaffMember.all_objects.create(workspace=workspace, user=user, role=role, is_active=True)
    assign_workspace_owner(workspace, user)
    return user


def _console(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def test_the_console_shows_an_archived_extension_and_where_it_went(workspace, store, owner):
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')

    response = _console(owner).get(f'/api/v1/platform/console/workspaces/{workspace.pk}/')

    entry = next(item for item in response.json()['extensions'] if item['key'] == 'notes')
    assert (entry['status'], entry['status_reason']) == ('archived', archive.REASON_ARCHIVED)
    assert entry['archive']['rows'] == 5
    assert entry['archive']['archived_at']
    # An owner is shown what happened, not the deployment's storage layout.
    assert 'location' not in entry['archive']


def test_the_console_restores_an_archived_extension(workspace, store, owner):
    _switched_off(workspace)
    _fill(workspace)
    archive.archive(workspace, 'notes')

    response = _console(owner).post(
        f'/api/v1/platform/console/workspaces/{workspace.pk}/extensions/notes/restore/'
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'active'
    assert _rows(workspace) == (1, 2, 2)


def test_the_console_reports_why_a_restore_was_refused(workspace, store, owner):
    _switched_off(workspace)

    response = _console(owner).post(
        f'/api/v1/platform/console/workspaces/{workspace.pk}/extensions/notes/restore/'
    )

    assert response.status_code == 400
    assert response.json()['code'] == 'not_archived'


def test_the_console_says_when_the_deployment_archives_nothing(workspace, settings, owner):
    settings.BFG_EXTENSION_ARCHIVE_STORAGE = ''
    _switched_off(workspace)

    response = _console(owner).post(
        f'/api/v1/platform/console/workspaces/{workspace.pk}/extensions/notes/restore/'
    )

    assert response.status_code == 409
    assert response.json()['code'] == 'archive_not_configured'

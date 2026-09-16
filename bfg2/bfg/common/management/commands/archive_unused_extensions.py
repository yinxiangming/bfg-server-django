# -*- coding: utf-8 -*-
"""
Archive the data of extensions that workspaces stopped using long enough ago.

Each one is exported to private storage, read back and checked, and only then are its
rows deleted — see ``bfg.common.extensions.archive`` for what is refused and why. An
extension counts as unused once it has been switched off or paused for
``archive_after_days``, which is a platform variable rather than a release.

**There is no scheduler behind this.** Neither deployment runs Celery beat, so it has to
be called — by cron, by hand, by whatever the deployment can offer — ideally once a day.
Nothing is lost by running it late; an extension simply keeps its rows until it runs.
Running it twice in a row does nothing the second time, and an extension it refused is
refused again with the same reason rather than half-done.

Archiving is off until ``BFG_EXTENSION_ARCHIVE_STORAGE`` names private storage to write
to, and this says so and stops rather than deleting anything.

Usage:

    python manage.py archive_unused_extensions
    python manage.py archive_unused_extensions --dry-run
    python manage.py archive_unused_extensions --workspace acme --limit 5

    # archive one extension of one workspace now, without waiting out the days
    python manage.py archive_unused_extensions --workspace acme --key some_key --ignore-age
"""
from django.core.management.base import BaseCommand, CommandError

from bfg.common.extensions import archive
from bfg.common.models import Workspace


class Command(BaseCommand):
    help = "Export and delete the data of extensions that have been switched off for long enough"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help=(
                'Run every check and count the rows each archive would hold, writing nothing, '
                'deleting nothing and changing no status.'
            ),
        )
        parser.add_argument('--workspace', help='Only this workspace, by id or slug.')
        parser.add_argument('--key', help='Only this extension.')
        parser.add_argument('--limit', type=int, help='Archive at most this many in one run.')
        parser.add_argument(
            '--ignore-age',
            action='store_true',
            help=(
                'Archive even though it has not been switched off for long enough. Needs '
                '--workspace and --key, so it can only ever mean one extension of one workspace.'
            ),
        )

    def handle(self, *args, **options):
        workspace = self._workspace(options['workspace'])
        if options['ignore_age'] and not (workspace and options['key']):
            raise CommandError('--ignore-age needs both --workspace and --key.')

        try:
            report = archive.sweep(
                workspace=workspace,
                key=options['key'],
                limit=options['limit'],
                ignore_age=options['ignore_age'],
                dry_run=options['dry_run'],
            )
        except archive.ArchiveNotConfigured as unconfigured:
            raise CommandError(unconfigured.reason)

        for released in report['released']:
            self.stdout.write(self.style.WARNING(
                f'  released  {released["key"]} @ workspace {released["workspace_id"]}: '
                f'was {released["was"]} with nothing running it, now {released["status"]}'
            ))
        for done in report['archived']:
            self.stdout.write(
                f'  {"would archive" if report["dry_run"] else "archived"}  '
                f'{done["key"]} @ workspace {done["workspace_id"]}: '
                f'{done["rows"]} rows in {done["tables"]} tables'
                + (f'  →  {done["location"]}' if done.get('location') else '')
            )
        for refused in report['refused']:
            self.stderr.write(
                f'  refused  {refused["key"]} @ workspace {refused["workspace_id"]}: '
                f'{refused["code"]}: {refused["detail"]}'
            )

        if not (report['archived'] or report['refused'] or report['released']):
            self.stdout.write('No extension has been switched off for long enough.')
            return

        self.stdout.write('')
        if report['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'Dry run: {len(report["archived"])} extensions would be archived, '
                f'{len(report["refused"])} refused. Nothing was written or deleted.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'{len(report["archived"])} extensions archived, {len(report["refused"])} refused.'
            ))

    @staticmethod
    def _workspace(identifier):
        if not identifier:
            return None
        lookup = {'pk': int(identifier)} if identifier.isdigit() else {'slug': identifier}
        workspace = Workspace.objects.filter(**lookup).first()
        if workspace is None:
            raise CommandError(f'No workspace {identifier!r}.')
        return workspace

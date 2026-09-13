# -*- coding: utf-8 -*-
"""
List and switch workspace extensions from the shell.

    manage.py workspace_extensions list [--workspace ID_OR_SLUG ...]
    manage.py workspace_extensions activate KEY --workspace ID_OR_SLUG [--workspace ...]
    manage.py workspace_extensions deactivate KEY --workspace ID_OR_SLUG [--workspace ...]

Changes go through the same service as the extension API, so requirements,
prerequisites, entitlement and hooks all apply. Every workspace named is looked up before
anything changes. Each is then changed in its own transaction: a refusal for one is
reported without holding back the rest, and the command fails once all have been tried.
"""

from django.core.management.base import BaseCommand, CommandError

from bfg.common.extensions import registry, services
from bfg.common.models import Workspace, WorkspaceExtension

ROW = '{key:<24} {workspace:>9}  {slug:<32} {status:<10} {available}'


class Command(BaseCommand):
    help = 'List, activate or deactivate extensions for workspaces.'

    def add_arguments(self, parser):
        subcommands = parser.add_subparsers(dest='subcommand', required=True)

        listing = subcommands.add_parser('list', help='Show which workspaces use which extensions.')
        listing.add_argument(
            '--workspace',
            action='append',
            default=[],
            help='Workspace id or slug; repeat for several. Without it, every workspace using an extension is listed.',
        )

        for name, help_text in (
            ('activate', 'Switch an extension on.'),
            ('deactivate', 'Switch an extension off, keeping its data and configuration.'),
        ):
            change = subcommands.add_parser(name, help=help_text)
            change.add_argument('key', help='Extension key.')
            change.add_argument(
                '--workspace',
                action='append',
                required=True,
                help='Workspace id or slug; repeat for several.',
            )

    def handle(self, *args, **options):
        if options['subcommand'] == 'list':
            self._list(self._workspaces(options['workspace']) if options['workspace'] else None)
        else:
            self._change(options['subcommand'], options['key'], self._workspaces(options['workspace']))

    def _workspaces(self, identifiers):
        workspaces = []
        for identifier in identifiers:
            lookup = {'pk': int(identifier)} if identifier.isdigit() else {'slug': identifier}
            workspace = Workspace.objects.filter(**lookup).first()
            if workspace is None:
                raise CommandError(f'No workspace {identifier!r}.')
            if workspace not in workspaces:
                workspaces.append(workspace)
        return workspaces

    def _list(self, workspaces):
        manifests = [manifest for manifest in registry.all_manifests() if manifest.is_activatable]
        records = WorkspaceExtension.all_objects.select_related('workspace').filter(
            key__in=[manifest.key for manifest in manifests]
        )
        if workspaces is None:
            rows = [(record.workspace, record.key, record) for record in records.order_by('key', 'workspace_id')]
        else:
            found = {(record.workspace_id, record.key): record for record in records.filter(workspace__in=workspaces)}
            rows = [
                (workspace, manifest.key, found.get((workspace.pk, manifest.key)))
                for manifest in manifests
                for workspace in workspaces
            ]

        self.stdout.write(
            ROW.format(key='EXTENSION', workspace='WORKSPACE', slug='SLUG', status='STATUS', available='AVAILABLE')
        )
        available = {}
        for workspace, key, record in rows:
            if workspace.pk not in available:
                available[workspace.pk] = services.compute_available_keys(workspace)
            self.stdout.write(
                ROW.format(
                    key=key,
                    workspace=workspace.pk,
                    slug=workspace.slug,
                    status=record.status if record else '-',
                    available='yes' if key in available[workspace.pk] else 'no',
                )
            )

    def _change(self, subcommand, key, workspaces):
        manifest = registry.get_manifest(key)
        if manifest is None:
            raise CommandError(f'No extension named {key!r} is deployed.')
        if not manifest.is_activatable:
            raise CommandError(f'{key} is always available and cannot be switched on or off.')

        change = services.activate if subcommand == 'activate' else services.deactivate
        refused = 0
        for workspace in workspaces:
            try:
                record = change(workspace, key)
            except services.ExtensionError as exc:
                refused += 1
                self.stderr.write(f'{workspace.pk} {workspace.slug}: {exc.code}: {exc.message}')
                continue
            self.stdout.write(f'{workspace.pk} {workspace.slug}: {key} {record.status if record else "not used"}')
        if refused:
            raise CommandError(f'{refused} of {len(workspaces)} workspaces were not changed.')

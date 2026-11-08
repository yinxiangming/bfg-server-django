"""Process due messages from a scheduler or an operator's command line."""

import json

from django.core.management.base import BaseCommand, CommandError

from bfg.common.services.email_outbox import process_due


class Command(BaseCommand):
    help = 'Send due persisted emails and recover expired worker leases.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--workspace', type=int, dest='workspace_id')

    def handle(self, *args, **options):
        try:
            report = process_due(limit=options['limit'], workspace_id=options['workspace_id'])
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(report, sort_keys=True))

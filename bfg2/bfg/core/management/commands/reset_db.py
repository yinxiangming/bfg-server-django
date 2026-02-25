# -*- coding: utf-8 -*-
"""
Drop all tables in the default database. Only allowed in non-prod environment.
Use before re-running migrate after clearing and regenerating migrations.
Usage: python manage.py reset_db
"""

import os
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Drop all tables in the default database (non-prod only; for migration reset flow)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Do not prompt for confirmation',
        )

    def handle(self, *args, **options):
        env = os.environ.get('ENV', 'dev').lower().strip()
        if env == 'prod':
            self.stdout.write(self.style.ERROR('reset_db is not allowed in prod environment.'))
            return
        if not options['no_input']:
            confirm = input('Drop all tables in the database? Type "yes" to continue: ')
            if confirm != 'yes':
                self.stdout.write('Aborted.')
                return

        with connection.cursor() as cursor:
            vendor = connection.vendor
            if vendor == 'mysql':
                cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
                )
                tables = [row[0] for row in cursor.fetchall()]
                for table in tables:
                    cursor.execute(f'DROP TABLE IF EXISTS `{table}`')
                cursor.execute('SET FOREIGN_KEY_CHECKS = 1')
                self.stdout.write(self.style.SUCCESS(f'Dropped {len(tables)} tables.'))
            elif vendor == 'sqlite3':
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [row[0] for row in cursor.fetchall()]
                for table in tables:
                    cursor.execute(f'DROP TABLE IF EXISTS "{table}"')
                self.stdout.write(self.style.SUCCESS(f'Dropped {len(tables)} tables.'))
            else:
                self.stdout.write(self.style.ERROR(f'Unsupported database vendor: {vendor}'))
                return

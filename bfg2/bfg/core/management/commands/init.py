# -*- coding: utf-8 -*-
"""
Create initial workspace and superadmin user. Optionally run seed_data.
Usage: python manage.py init [--workspace-name NAME] [--workspace-slug SLUG] [--superadmin USERNAME] [--seed-data|--no-seed-data]
"""

import os
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model
from bfg.common.models import Workspace, StaffRole, StaffMember
from bfg.common.utils import create_staff_roles
from bfg.core.events import global_dispatcher

User = get_user_model()

DEFAULT_WORKSPACE_NAME = 'Default Workspace'
DEFAULT_WORKSPACE_SLUG = 'default'
DEFAULT_SUPERADMIN_USERNAME = 'superadmin'


def ensure_workspace_roles(workspace):
    """Ensure admin role exists for workspace."""
    core_roles = [
        {
            'code': 'admin',
            'name': 'Administrator',
            'description': 'Full access to all workspace resources',
            'permissions': {'*': ['create', 'read', 'update', 'delete']},
            'is_system': True,
        },
    ]
    create_staff_roles(workspace, core_roles)


class Command(BaseCommand):
    help = 'Create initial workspace and superadmin user; optionally import seed_data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--workspace-name',
            type=str,
            default=DEFAULT_WORKSPACE_NAME,
            help=f'Workspace display name (default: {DEFAULT_WORKSPACE_NAME})',
        )
        parser.add_argument(
            '--workspace-slug',
            type=str,
            default=DEFAULT_WORKSPACE_SLUG,
            help=f'Workspace slug (default: {DEFAULT_WORKSPACE_SLUG})',
        )
        parser.add_argument(
            '--superadmin',
            type=str,
            default=DEFAULT_SUPERADMIN_USERNAME,
            dest='superadmin_username',
            help=f'Superadmin username (default: {DEFAULT_SUPERADMIN_USERNAME})',
        )
        parser.add_argument(
            '--seed-data',
            action='store_true',
            help='Import seed_data after creating workspace and user',
        )
        parser.add_argument(
            '--no-seed-data',
            action='store_true',
            help='Do not import seed_data (skip prompt when non-interactive)',
        )

    def handle(self, *args, **options):
        workspace_name = options['workspace_name']
        workspace_slug = options['workspace_slug']
        superadmin_username = options['superadmin_username']
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')

        # 1. Create or get workspace
        workspace, ws_created = Workspace.objects.get_or_create(
            slug=workspace_slug,
            defaults={
                'name': workspace_name,
                'domain': 'localhost',
                'is_active': True,
            },
        )
        if ws_created:
            self.stdout.write(self.style.SUCCESS(f'Created workspace: {workspace.name} (slug={workspace_slug})'))
            global_dispatcher.dispatch('workspace.created', {'data': {'workspace': workspace}})
        else:
            self.stdout.write(self.style.WARNING(f'Workspace already exists: {workspace.name}'))

        if not StaffRole.objects.filter(workspace=workspace, code='admin').exists():
            ensure_workspace_roles(workspace)
            if not ws_created:
                self.stdout.write(self.style.SUCCESS('Added admin role to workspace'))

        # 2. Create or get superadmin user
        user, user_created = User.objects.get_or_create(
            username=superadmin_username,
            defaults={
                'email': f'{superadmin_username}@localhost',
                'first_name': 'Super',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
                'default_workspace': workspace,
            },
        )
        if user_created:
            user.set_password(admin_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created superadmin: {user.username}'))
        else:
            if not user.is_superuser:
                user.is_superuser = True
                user.is_staff = True
                user.save(update_fields=['is_superuser', 'is_staff'])
            if user.default_workspace_id != workspace.id:
                user.default_workspace = workspace
                user.save(update_fields=['default_workspace'])
            user.set_password(admin_password)
            user.save()
            self.stdout.write(self.style.WARNING(f'Superadmin already exists: {user.username} (password updated)'))

        admin_role = StaffRole.objects.get(workspace=workspace, code='admin')
        _, sm_created = StaffMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={'role': admin_role, 'is_active': True},
        )
        if sm_created:
            self.stdout.write(self.style.SUCCESS(f'Assigned {user.username} as workspace admin'))

        # 3. Optional seed_data
        do_seed = options['seed_data']
        if not do_seed and not options['no_seed_data']:
            try:
                answer = input('Import seed_data? [y/N]: ').strip().lower()
                do_seed = answer in ('y', 'yes')
            except (EOFError, KeyboardInterrupt):
                do_seed = False

        if do_seed:
            self.stdout.write(self.style.SUCCESS('Running seed_data...'))
            call_command('seed_data', stdout=self.stdout)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Workspace id: {workspace.id}'))
        self.stdout.write(f'Login: {superadmin_username} / {admin_password}')

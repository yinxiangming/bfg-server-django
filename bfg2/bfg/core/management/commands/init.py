# -*- coding: utf-8 -*-
"""
Create initial workspace and admin user. Optionally run migrate, seed_data, and load site config.
Usage: python manage.py init [--workspace-name NAME] [--workspace-slug SLUG] [--admin USERNAME] [--seed-data|--no-seed-data]
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model

from bfg.common.models import Workspace, StaffRole, StaffMember
from bfg.common.utils import create_staff_roles
from bfg.core.events import global_dispatcher
from bfg.web.services import SiteConfigService

User = get_user_model()

DEFAULT_WORKSPACE_NAME = 'Default Workspace'
DEFAULT_WORKSPACE_SLUG = 'default'
DEFAULT_ADMIN_USERNAME = 'admin'


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


def get_default_site_config_path():
    """Default path: bfg2/seed_media/site-config-xmart.json (source tree)."""
    base = Path(__file__).resolve().parent
    for _ in range(4):
        base = base.parent
    return base / 'seed_media' / 'site-config-xmart.json'


class Command(BaseCommand):
    help = 'Create initial workspace and admin user; optionally run migrate, import seed_data, load site config'

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
            '--admin',
            type=str,
            default=DEFAULT_ADMIN_USERNAME,
            dest='admin_username',
            help=f'Admin username (default: {DEFAULT_ADMIN_USERNAME})',
        )
        parser.add_argument(
            '--seed-data',
            action='store_true',
            help='Import seed_data and load site config (bfg2/seed_media/site-config-xmart.json)',
        )
        parser.add_argument(
            '--no-seed-data',
            action='store_true',
            help='Do not import seed_data or load site config (skip prompt when non-interactive)',
        )
        parser.add_argument(
            '--no-migrate',
            action='store_true',
            help='Skip running migrate at the start',
        )
        parser.add_argument(
            '--site-config',
            type=str,
            default=None,
            help='Path to site-config JSON (default: bfg2/seed_media/site-config-xmart.json)',
        )

    def handle(self, *args, **options):
        workspace_name = options['workspace_name']
        workspace_slug = options['workspace_slug']
        admin_username = options['admin_username']

        # 0. Run migrate unless disabled
        if not options['no_migrate']:
            self.stdout.write('Running migrate...')
            call_command('migrate', stdout=self.stdout)
            self.stdout.write(self.style.SUCCESS('Migrate done.'))

        # Prompt for password (no default, no env)
        try:
            admin_password = self.get_password(admin_username)
        except (EOFError, KeyboardInterrupt):
            self.stdout.write('Aborted.')
            return
        if not admin_password:
            self.stdout.write(self.style.ERROR('Password is required.'))
            return

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

        # 2. Create or get admin user
        user, user_created = User.objects.get_or_create(
            username=admin_username,
            defaults={
                'email': f'{admin_username}@localhost',
                'first_name': 'Admin',
                'last_name': 'User',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
                'default_workspace': workspace,
            },
        )
        if user_created:
            user.set_password(admin_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created admin: {user.username}'))
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
            self.stdout.write(self.style.WARNING(f'Admin already exists: {user.username} (password updated)'))

        admin_role = StaffRole.objects.get(workspace=workspace, code='admin')
        _, sm_created = StaffMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={'role': admin_role, 'is_active': True},
        )
        if sm_created:
            self.stdout.write(self.style.SUCCESS(f'Assigned {user.username} as workspace admin'))

        # 3. Optional seed_data + site config
        do_seed = options['seed_data']
        if not do_seed and not options['no_seed_data']:
            try:
                answer = input('Import seed_data and load site config (bfg2/seed_media/site-config-xmart.json)? [y/N]: ').strip().lower()
                do_seed = answer in ('y', 'yes')
            except (EOFError, KeyboardInterrupt):
                do_seed = False

        if do_seed:
            self.stdout.write(self.style.SUCCESS('Running seed_data...'))
            call_command('seed_data', workspace=workspace_slug, stdout=self.stdout)
            # Load site config for storefront (Site, Pages, Menus)
            config_path = options.get('site_config')
            if not config_path:
                default_path = get_default_site_config_path()
                if default_path.exists():
                    config_path = str(default_path)
            if config_path and Path(config_path).exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                service = SiteConfigService(workspace=workspace, user=user)
                service.load_from_config(config, created_by_user=user, mode='merge')
                from django.core.cache import cache
                for lang in ('en', 'zh-hans'):
                    cache.delete(f'storefront_config:{workspace.id}:{lang}')
                self.stdout.write(self.style.SUCCESS('Loaded site config (Site, Pages, Menus).'))
            else:
                self.stdout.write(
                    self.style.WARNING('Site config not found (expected bfg2/seed_media/site-config-xmart.json).')
                )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Workspace id: {workspace.id}'))
        self.stdout.write(f'Login: {admin_username} / (password you entered)')

    def get_password(self, username):
        """Prompt for admin password (with confirmation)."""
        from getpass import getpass
        p1 = getpass(f'Password for {username}: ')
        if not p1:
            return ''
        p2 = getpass('Password (again): ')
        if p1 != p2:
            self.stdout.write(self.style.ERROR('Passwords do not match.'))
            return ''
        return p1

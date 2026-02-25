# -*- coding: utf-8 -*-
"""
Create "web" workspace, webadmin user, and load XMart site config.
Usage: python manage.py init_web_workspace [--no-load-site]
Outputs workspace id for use with client: PORT=3001 NEXT_PUBLIC_WORKSPACE_ID=<id> npm run dev
"""

import os
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from bfg.common.models import Workspace, StaffRole, StaffMember
from bfg.core.events import global_dispatcher
from bfg.web.services import SiteConfigService

User = get_user_model()


def ensure_workspace_roles(workspace):
    """Ensure admin (and staff) roles exist for workspace (e.g. after manual create)."""
    from bfg.common.utils import create_staff_roles
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
    help = 'Create web workspace, webadmin user, and load site config for sales site'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-load-site',
            action='store_true',
            help='Skip loading site-config-xmart.json',
        )
        parser.add_argument(
            '--config',
            type=str,
            default=None,
            help='Path to site config JSON (default: web/design/site-config-xmart.json relative to project)',
        )

    def handle(self, *args, **options):
        # 1. Get or create workspace "web"
        workspace, ws_created = Workspace.objects.get_or_create(
            slug='web',
            defaults={
                'name': 'Web',
                'domain': 'localhost:3001',
                'is_active': True,
            },
        )
        if ws_created:
            self.stdout.write(self.style.SUCCESS(f'Created workspace: {workspace.name} (slug=web)'))
            global_dispatcher.dispatch('workspace.created', {'data': {'workspace': workspace}})
        else:
            if not StaffRole.objects.filter(workspace=workspace, code='admin').exists():
                ensure_workspace_roles(workspace)
                self.stdout.write(self.style.WARNING('Added admin role to existing web workspace'))

        # 2. Get or create webadmin user
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        user, user_created = User.objects.get_or_create(
            username='webadmin',
            defaults={
                'email': 'webadmin@localhost',
                'first_name': 'Web',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
                'default_workspace': workspace,
            },
        )
        if user_created:
            user.set_password(admin_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created user: {user.username}'))
        else:
            if user.default_workspace_id != workspace.id:
                user.default_workspace = workspace
                user.save(update_fields=['default_workspace'])
        admin_role = StaffRole.objects.get(workspace=workspace, code='admin')
        _, sm_created = StaffMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={'role': admin_role, 'is_active': True},
        )
        if sm_created:
            self.stdout.write(self.style.SUCCESS(f'Assigned {user.username} as workspace admin'))

        # 3. Load site config
        if not options['no_load_site']:
            config_path = options.get('config')
            if not config_path:
                # Default: project root is server's parent (e.g. bfg_v2), web/design is sibling of server
                base = Path(__file__).resolve().parent
                for _ in range(5):
                    base = base.parent
                project_root = base.parent
                candidate = project_root / 'web' / 'design' / 'site-config-xmart.json'
                if candidate.exists():
                    config_path = str(candidate)
            if config_path and Path(config_path).exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                service = SiteConfigService(workspace=workspace, user=user)
                service.load_from_config(config, created_by_user=user, mode='merge')
                self.stdout.write(self.style.SUCCESS('Loaded site config (Site, Pages, Menus)'))
            else:
                self.stdout.write(self.style.WARNING('Site config not found (expected web/design/site-config-xmart.json); skip with --no-load-site'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Workspace id: {workspace.id}'))
        self.stdout.write('Start client on port 3001 with this workspace:')
        self.stdout.write(f'  cd client && PORT=3001 NEXT_PUBLIC_WORKSPACE_ID={workspace.id} npm run dev')
        self.stdout.write('Login: webadmin / ' + admin_password)

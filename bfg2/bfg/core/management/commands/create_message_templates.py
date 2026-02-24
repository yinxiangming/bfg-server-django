# -*- coding: utf-8 -*-
"""
Django management command to create order notification message templates.
Usage: 
    python manage.py create_message_templates
    python manage.py create_message_templates --workspace demo
    python manage.py create_message_templates --workspace-id 1
    python manage.py create_message_templates --all
"""

from django.core.management.base import BaseCommand, CommandError
from bfg.common.models import Workspace
from bfg.shop.seed_data import create_order_notification_templates


class Command(BaseCommand):
    help = 'Create order notification message templates for specific workspace(s)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--workspace',
            type=str,
            help='Workspace slug (e.g., "demo")',
        )
        parser.add_argument(
            '--workspace-id',
            type=int,
            help='Workspace ID (e.g., 1)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Create templates for all active workspaces',
        )

    def handle(self, *args, **options):
        workspaces = []
        
        # Determine which workspace(s) to use
        if options.get('all'):
            # Create for all active workspaces
            workspaces = list(Workspace.objects.filter(is_active=True).order_by('id'))
            if not workspaces:
                raise CommandError('No active workspaces found.')
            self.stdout.write(self.style.SUCCESS(f'Found {len(workspaces)} active workspace(s)'))
        elif options.get('workspace_id'):
            # Get by ID
            try:
                workspace = Workspace.objects.get(id=options['workspace_id'], is_active=True)
                workspaces = [workspace]
            except Workspace.DoesNotExist:
                raise CommandError(f'Workspace with ID {options["workspace_id"]} not found or not active.')
        elif options.get('workspace'):
            # Get by slug
            try:
                workspace = Workspace.objects.get(slug=options['workspace'], is_active=True)
                workspaces = [workspace]
            except Workspace.DoesNotExist:
                raise CommandError(f'Workspace with slug "{options["workspace"]}" not found or not active.')
        else:
            # Default: use first active workspace
            workspace = Workspace.objects.filter(is_active=True).first()
            if not workspace:
                raise CommandError('No active workspace found. Use --workspace, --workspace-id, or --all to specify.')
            workspaces = [workspace]
            self.stdout.write(self.style.WARNING('No workspace specified, using first active workspace.'))
        
        # Create templates for each workspace
        total_created = 0
        for workspace in workspaces:
            self.stdout.write(self.style.SUCCESS(f'\n📦 Processing workspace: {workspace.name} (ID: {workspace.id}, Slug: {workspace.slug})'))
            
            # Create templates
            try:
                templates = create_order_notification_templates(
                    workspace=workspace,
                    stdout=self.stdout,
                    style=self.style
                )
                total_created += len(templates)
                self.stdout.write(self.style.SUCCESS(f'✅ Created/updated {len(templates)} message templates for {workspace.name}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Failed to create templates for {workspace.name}: {str(e)}'))
                import traceback
                self.stdout.write(self.style.ERROR(traceback.format_exc()))
        
        # Summary
        if len(workspaces) > 1:
            self.stdout.write(self.style.SUCCESS(f'\n✅ Total: Created/updated templates for {len(workspaces)} workspace(s), {total_created} templates in total.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\n✅ Created/updated {total_created} message templates.'))

"""
Initialize System Roles

Django management command: Initialize system default roles
"""

from django.core.management.base import BaseCommand
from bfg.common.models import StaffRole


class Command(BaseCommand):
    help = 'Initialize system default roles'
    
    def handle(self, *args, **options):
        self.stdout.write('Initializing system roles...')
        
        # System role definitions
        system_roles = [
            {
                'code': 'admin',
                'name': 'Administrator',
                'description': 'Full access to all workspace resources',
                'permissions': {
                    '*': ['create', 'read', 'update', 'delete']
                },
                'is_system': True,
            },
            {
                'code': 'store_admin',
                'name': 'Store Administrator',
                'description': 'Manage store settings, products, and orders',
                'permissions': {
                    'shop.store': ['read', 'update'],
                    'shop.product': ['create', 'read', 'update', 'delete'],
                    'shop.category': ['create', 'read', 'update', 'delete'],
                    'shop.order': ['read', 'update'],
                    'delivery.consignment': ['create', 'read', 'update'],
                },
                'is_system': True,
            },
            {
                'code': 'warehouse_manager',
                'name': 'Warehouse Manager',
                'description': 'Manage inventory and shipments',
                'permissions': {
                    'delivery.warehouse': ['read', 'update'],
                    'delivery.manifest': ['create', 'read', 'update'],
                    'delivery.consignment': ['create', 'read', 'update'],
                    'shop.inventory': ['read', 'update'],
                },
                'is_system': True,
            },
            {
                'code': 'customer_service',
                'name': 'Customer Service',
                'description': 'Handle customer inquiries and support',
                'permissions': {
                    'shop.order': ['read'],
                    'support.ticket': ['create', 'read', 'update'],
                    'common.customer': ['read'],
                },
                'is_system': True,
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        # Note: This command should be executed in each workspace context
        # or modified to accept workspace_id parameter
        from bfg.common.models import Workspace
        for workspace in Workspace.objects.filter(is_active=True):
            for role_data in system_roles:
                role, created = StaffRole.objects.update_or_create(
                    workspace=workspace,
                    code=role_data['code'],
                    defaults={
                        'name': role_data['name'],
                        'description': role_data['description'],
                        'permissions': role_data['permissions'],
                        'is_system': role_data['is_system'],
                        'is_active': True,
                    }
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Created role: {role.name} (Workspace: {workspace.name})'
                        )
                    )
                else:
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'↻ Updated role: {role.name} (Workspace: {workspace.name})'
                        )
                    )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone! Created {created_count} roles, updated {updated_count} roles'
            )
        )

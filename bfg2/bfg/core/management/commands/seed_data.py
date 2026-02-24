# -*- coding: utf-8 -*-
"""
Django management command to seed database with sample data.
Usage: python manage.py seed_data
"""

import os
import shutil
import importlib
import pkgutil
from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from bfg.common.models import Workspace


class Command(BaseCommand):
    help = 'Seed database with sample data for development and testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before seeding',
        )
        parser.add_argument(
            '--copy-images',
            action='store_true',
            help='Copy sample images from full-version to media directory',
        )
        parser.add_argument(
            '--module',
            type=str,
            help='Seed specific module(s). Can be a single module name or comma-separated list (e.g., "common,delivery"). If not specified, all available modules will be seeded.',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting database seeding...'))
        
        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing existing data...'))
            self.clear_data(options.get('module'))
            self.stdout.write(self.style.SUCCESS('Clear completed. Run seed_data without --clear to re-import.'))
            return

        if options['copy_images']:
            self.copy_sample_images()
        
        # Create workspace first (required by all modules)
        workspace = self.create_workspace()
        
        # Get module list
        modules = self.get_modules_to_seed(options.get('module'))
        
        # Seed data for each module; each module may return 'summary' list for display
        self.summaries = []
        context = {'workspace': workspace}
        for module_name in modules:
            try:
                self.seed_module(module_name, context)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error seeding {module_name}: {str(e)}'))
                import traceback
                traceback.print_exc()
        
        self.stdout.write(self.style.SUCCESS('\n✅ Database seeding completed successfully!'))
        self.print_summary()

    def discover_modules(self):
        """Automatically discover all modules with seed_data.py"""
        modules = []
        
        try:
            # Import bfg package
            import bfg
            bfg_path = os.path.dirname(bfg.__file__)
            
            # Walk through bfg package to find modules with seed_data.py
            for finder, name, ispkg in pkgutil.iter_modules([bfg_path]):
                if ispkg and name != 'core':  # Skip core module itself
                    # Try to import seed_data module to verify it exists and has seed_data function
                    try:
                        module = importlib.import_module(f'bfg.{name}.seed_data')
                        if hasattr(module, 'seed_data') and callable(module.seed_data):
                            modules.append(name)
                    except (ImportError, AttributeError, ModuleNotFoundError):
                        pass
            
            # Also check apps directory for new modules
            try:
                import apps
                apps_path = os.path.dirname(apps.__file__)
                for finder, name, ispkg in pkgutil.iter_modules([apps_path]):
                    if ispkg:
                        try:
                            module = importlib.import_module(f'apps.{name}.seed_data')
                            if hasattr(module, 'seed_data') and callable(module.seed_data):
                                modules.append(f'apps.{name}')
                        except (ImportError, AttributeError, ModuleNotFoundError):
                            pass
            except ImportError:
                # apps package is optional
                self.stdout.write(self.style.WARNING(
                    'apps package not found. Skipping apps modules.'
                ))
        except Exception as e:
            # Fallback to manual list if discovery fails
            self.stdout.write(self.style.WARNING(
                f'Module discovery failed: {e}. Using fallback list.'
            ))
            modules = ['common', 'delivery', 'web', 'shop', 'marketing', 'support', 'finance', 'inbox']
        
        # Prefer order: shop before marketing so CampaignDisplay rules get ProductCategory
        seed_order = ['common', 'delivery', 'web', 'shop', 'marketing', 'support', 'finance', 'inbox']
        order_index = {m: i for i, m in enumerate(seed_order)}
        return sorted(modules, key=lambda m: (order_index.get(m, len(seed_order)), m))

    def get_clear_order(self, modules):
        """Return modules in clear order: dependents first so FKs are safe (e.g. marketing before finance, shop/delivery before common)."""
        clear_order = ['inbox', 'marketing', 'finance', 'support', 'web', 'shop', 'delivery', 'common']
        order_index = {m: i for i, m in enumerate(clear_order)}
        return sorted(modules, key=lambda m: (order_index.get(m, len(clear_order)), m))

    def get_modules_to_seed(self, module_filter=None):
        """Get list of modules to seed"""
        # Discover all available modules
        all_modules = self.discover_modules()
        
        if not module_filter:
            return all_modules
        
        # Support comma-separated module names
        requested_modules = [m.strip() for m in module_filter.split(',')]
        
        # Validate requested modules
        valid_modules = []
        invalid_modules = []
        for module_name in requested_modules:
            if module_name in all_modules:
                valid_modules.append(module_name)
            else:
                invalid_modules.append(module_name)
        
        if invalid_modules:
            self.stdout.write(self.style.ERROR(
                f'Unknown module(s): {", ".join(invalid_modules)}'
            ))
            self.stdout.write(self.style.WARNING(
                f'Available modules: {", ".join(all_modules)}'
            ))
        
        return valid_modules

    def seed_module(self, module_name, context):
        """Seed data for a specific module"""
        self.stdout.write(self.style.SUCCESS(f'\n📦 Seeding {module_name} module...'))
        
        try:
            # Import module's seed_data - handle both bfg.* and apps.* modules
            if module_name.startswith('apps.'):
                module = __import__(f'{module_name}.seed_data', fromlist=['seed_data'])
            else:
                module = __import__(f'bfg.{module_name}.seed_data', fromlist=['seed_data'])
            
            # Prepare kwargs - workspace is already in context, so pass context directly
            kwargs = {
                'stdout': self.stdout,
                'style': self.style,
            }
            kwargs.update(context)
            
            # Call seed_data function
            result = module.seed_data(**kwargs)
            
            # Update context with returned data; collect summary from module
            if result:
                context.update(result)
                for item in result.get('summary', []):
                    self.summaries.append(item)
        except ImportError as e:
            self.stdout.write(self.style.WARNING(f'⚠️  Module {module_name} has no seed_data.py: {e}'))
        except AttributeError as e:
            self.stdout.write(self.style.WARNING(f'⚠️  Module {module_name}.seed_data has no seed_data function: {e}'))

    def clear_data(self, module_filter=None):
        """Clear in dependency order: dependents first (e.g. marketing GiftCard before finance Currency; shop/delivery Order/Consignment before common Address)."""
        modules = self.get_modules_to_seed(module_filter)
        for module_name in self.get_clear_order(modules):
            try:
                # Handle both bfg.* and apps.* modules
                if module_name.startswith('apps.'):
                    module = __import__(f'{module_name}.seed_data', fromlist=['clear_data'])
                else:
                    module = __import__(f'bfg.{module_name}.seed_data', fromlist=['clear_data'])
                    
                if hasattr(module, 'clear_data'):
                    self.stdout.write(self.style.WARNING(f'Clearing {module_name} data...'))
                    module.clear_data()
            except (ImportError, AttributeError):
                pass  # Module has no clear_data function

    def copy_sample_images(self):
        """Copy sample images from full-version to media directory"""
        source_dir = '/Users/mac/Projects/vuexy-ts/full-version/public/images'
        target_dir = os.path.join(settings.MEDIA_ROOT, 'seed_images')
        
        if not os.path.exists(source_dir):
            self.stdout.write(self.style.WARNING(f'Source directory not found: {source_dir}'))
            return
        
        os.makedirs(target_dir, exist_ok=True)
        
        # Copy avatars
        avatars_source = os.path.join(source_dir, 'avatars')
        avatars_target = os.path.join(target_dir, 'avatars')
        if os.path.exists(avatars_source):
            shutil.copytree(avatars_source, avatars_target, dirs_exist_ok=True)
            self.stdout.write(self.style.SUCCESS(f'✓ Copied avatars to {avatars_target}'))
        
        # Copy product images
        products_source = os.path.join(source_dir, 'apps', 'ecommerce')
        products_target = os.path.join(target_dir, 'products')
        if os.path.exists(products_source):
            shutil.copytree(products_source, products_target, dirs_exist_ok=True)
            self.stdout.write(self.style.SUCCESS(f'✓ Copied product images to {products_target}'))

    def create_workspace(self):
        """Create main workspace"""
        workspace, created = Workspace.objects.get_or_create(
            slug='demo',
            defaults={
                'name': 'Demo Workspace',
                'domain': 'localhost',
                'email': 'demo@localhost',
                'phone': '+64-21-555-0100',
                'is_active': True,
                'settings': {
                    'currency': 'NZD',
                    'timezone': 'Pacific/Auckland',
                    'language': 'en',
                }
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created workspace: {workspace.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'↻ Workspace already exists: {workspace.name}'))
        return workspace

    def print_summary(self):
        """Print summary from each module's seed_data return (summary key)."""
        self.stdout.write(self.style.SUCCESS('\n📊 Summary:'))
        for item in getattr(self, 'summaries', []):
            label = item.get('label', '')
            count = item.get('count', 0)
            if label:
                self.stdout.write(self.style.SUCCESS(f'   {label}: {count}'))


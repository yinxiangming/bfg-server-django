# -*- coding: utf-8 -*-
"""
Load site config (Site, Theme, Pages, Menus) from JSON file into a workspace.
Usage: python manage.py load_site_config <path-to-site-config.json> --workspace=<slug_or_id> [--replace] [--user=<id>]
"""

import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from bfg.common.utils import first_staff_user_for_workspace
from bfg.common.models import Workspace
from bfg.web.services import SiteConfigService

User = get_user_model()


class Command(BaseCommand):
    help = "Load site config from JSON into a workspace (bfg.web Site, Theme, Pages, Menus)"

    def add_arguments(self, parser):
        parser.add_argument("config_path", type=str, help="Path to site-config JSON file")
        parser.add_argument(
            "--workspace",
            type=str,
            required=True,
            help="Workspace slug or numeric id",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace existing web site data before import (default: merge)",
        )
        parser.add_argument(
            "--replace-shop-categories",
            action="store_true",
            help="When JSON includes 'categories', delete workspace ProductCategory rows before import (dev reset)",
        )
        parser.add_argument(
            "--user",
            type=int,
            default=None,
            help="User id for page created_by (default: first superuser)",
        )

    def handle(self, *args, **options):
        config_path = Path(options["config_path"]).resolve()
        if not config_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {config_path}"))
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Invalid JSON: {e}"))
            return
        ws_arg = options["workspace"].strip()
        try:
            workspace = Workspace.objects.get(id=int(ws_arg)) if ws_arg.isdigit() else Workspace.objects.get(slug=ws_arg)
        except Workspace.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Workspace not found: {ws_arg}"))
            return
        user = None
        if options.get("user"):
            try:
                user = User.objects.get(pk=options["user"])
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User id not found: {options['user']}"))
                return
        else:
            user = first_staff_user_for_workspace(workspace)
        if not user and config.get("pages"):
            self.stdout.write(
                self.style.WARNING(
                    "No user for created_by: pages require a user. Use --user=<id> or add a StaffMember to this workspace."
                )
            )
        mode = "replace" if options["replace"] else "merge"
        replace_shop_categories = bool(options.get("replace_shop_categories"))
        service = SiteConfigService(workspace=workspace, user=user)
        try:
            result = service.load_from_config(
                config,
                created_by_user=user,
                mode=mode,
                replace_shop_categories=replace_shop_categories,
            )
            from django.core.cache import cache
            for lang in ("en", "zh-hans"):
                cache.delete(f"storefront_config:{workspace.id}:{lang}")
            self.stdout.write(self.style.SUCCESS(f"Loaded site: {result.get('site')}"))
            self.stdout.write(self.style.SUCCESS(f"Pages: {len(result.get('pages', []))}"))
            self.stdout.write(self.style.SUCCESS(f"Menus: {result.get('menus_count', 0)}"))
            if result.get("categories_count"):
                self.stdout.write(self.style.SUCCESS(f"Categories: {result.get('categories_count')}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(str(e)))
            raise

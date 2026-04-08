# -*- coding: utf-8 -*-
"""
Create workspace from workspace_bootstrap in site-config JSON (if missing), then load site config.

Use on production after uploading the JSON file to the server:

  python manage.py bootstrap_workspace_from_site_config /path/to/site-config.json \\
    [--user=<staff_user_id>] [--replace] [--replace-shop-categories]

If a workspace with workspace_bootstrap.slug already exists, only the site config is imported.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.core.cache import cache

from bfg.common.models import Workspace
from bfg.common.services.workspace_service import WorkspaceService
from bfg.common.utils import first_staff_user_for_workspace
from bfg.web.services import SiteConfigService

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Create workspace from workspace_bootstrap block in JSON (if not exists), "
        "then load site config (Site, Theme, Pages, Menus, categories)."
    )

    def add_arguments(self, parser):
        parser.add_argument("config_path", type=str, help="Path to site-config JSON file")
        parser.add_argument(
            "--user",
            type=int,
            default=None,
            help="User id for workspace owner (new workspace) and page created_by (default: first superuser)",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace existing web site data before import (default: merge)",
        )
        parser.add_argument(
            "--replace-shop-categories",
            action="store_true",
            help="When JSON includes 'categories', delete workspace ProductCategory rows before import",
        )

    def handle(self, *args, **options):
        config_path = Path(options["config_path"]).resolve()
        if not config_path.exists():
            raise CommandError(f"File not found: {config_path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            raise CommandError(f"Invalid JSON: {e}") from e

        wb = config.get("workspace_bootstrap")
        if not wb or not isinstance(wb, dict):
            raise CommandError(
                "JSON must include a workspace_bootstrap object with at least name and slug "
                "(see site-config examples)."
            )

        slug = (wb.get("slug") or "").strip()
        name = (wb.get("name") or "").strip()
        if not slug:
            raise CommandError("workspace_bootstrap.slug is required")

        owner = None
        if options.get("user"):
            try:
                owner = User.objects.get(pk=options["user"])
            except User.DoesNotExist as e:
                raise CommandError(f"User id not found: {options['user']}") from e
        else:
            owner = User.objects.filter(is_superuser=True).first()
            if not owner:
                raise CommandError(
                    "No superuser found; create one or pass --user=<id> for workspace owner / page author."
                )

        site_domain = ""
        if isinstance(config.get("site"), dict):
            site_domain = (config["site"].get("domain") or "").strip()[:255]

        workspace = Workspace.objects.filter(slug=slug).first()
        if workspace:
            self.stdout.write(self.style.NOTICE(f"Using existing workspace: {slug} (id={workspace.id})"))
        else:
            if not name:
                raise CommandError("workspace_bootstrap.name is required when creating a new workspace")
            self.stdout.write(self.style.NOTICE(f"Creating workspace: {name} ({slug})"))
            ws_service = WorkspaceService(user=owner)
            workspace = ws_service.create_workspace(
                name=name,
                slug=slug,
                owner_user=owner,
                domain=site_domain or "",
            )
            self.stdout.write(self.style.SUCCESS(f"Created workspace id={workspace.id}"))

        user_for_pages = first_staff_user_for_workspace(workspace) or owner
        if not user_for_pages and config.get("pages"):
            self.stdout.write(
                self.style.WARNING(
                    "No staff user for page created_by; use --user or add StaffMember to this workspace."
                )
            )

        mode = "replace" if options["replace"] else "merge"
        replace_shop_categories = bool(options.get("replace_shop_categories"))
        service = SiteConfigService(workspace=workspace, user=user_for_pages)
        try:
            result = service.load_from_config(
                config,
                created_by_user=user_for_pages,
                mode=mode,
                replace_shop_categories=replace_shop_categories,
            )
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

        self.stdout.write(
            self.style.SUCCESS(
                "Done. Domain from site.domain is synced to WorkspaceDomain; "
                "ensure ALLOWED_HOSTS / CORS / CSRF include this hostname on the API."
            )
        )

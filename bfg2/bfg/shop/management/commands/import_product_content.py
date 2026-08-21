# -*- coding: utf-8 -*-
"""
Import SEO product copy (description / short_description / meta fields) into a workspace.

Products imported from a legacy catalogue often arrive with names and prices only. An empty
description means the product page has nothing for search engines to rank and nothing for
generative engines to quote, so this fills those fields from a JSON file keyed by product slug.

Non-destructive by default: only blank fields are written, so re-running after someone has
hand-edited copy in the admin will not clobber their work. Pass --overwrite to replace.

Usage:
    python manage.py import_product_content <path-to-json> --workspace=<slug_or_id> [--overwrite] [--dry-run]

JSON shape:
    {"<product-slug>": {"description": "...", "short_description": "...",
                        "meta_title": "...", "meta_description": "..."}, ...}
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.common.models import Workspace
from bfg.shop.models import Product

# Only these fields may be written; anything else in the JSON is ignored.
CONTENT_FIELDS = ("description", "short_description", "meta_title", "meta_description")


class Command(BaseCommand):
    help = "Import product descriptions and SEO meta fields from JSON, matched by slug"

    def add_arguments(self, parser):
        parser.add_argument("content_path", type=str, help="Path to product content JSON")
        parser.add_argument(
            "--workspace",
            type=str,
            required=True,
            help="Workspace slug or numeric id",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace existing copy (default: only fill fields that are currently blank)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing",
        )

    def handle(self, *args, **options):
        content_path = Path(options["content_path"]).resolve()
        if not content_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {content_path}"))
            return
        try:
            with open(content_path, "r", encoding="utf-8") as f:
                content = json.load(f)
        except (OSError, ValueError) as e:
            self.stdout.write(self.style.ERROR(f"Invalid JSON: {e}"))
            return

        ws_arg = options["workspace"].strip()
        try:
            workspace = (
                Workspace.objects.get(id=int(ws_arg))
                if ws_arg.isdigit()
                else Workspace.objects.get(slug=ws_arg)
            )
        except Workspace.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Workspace not found: {ws_arg}"))
            return

        overwrite = bool(options["overwrite"])
        dry_run = bool(options["dry_run"])

        # `Product.objects` is tenant-scoped and resolves the workspace from request
        # middleware, which does not exist in a management command — it would return an
        # empty queryset. `all_objects` is the un-scoped manager; the explicit
        # workspace filter below is what keeps this command single-tenant.
        products = {p.slug: p for p in Product.all_objects.filter(workspace=workspace)}
        missing = sorted(set(content) - set(products))
        untouched = sorted(set(products) - set(content))

        updated, skipped = 0, 0
        to_save = []

        for slug, fields in content.items():
            product = products.get(slug)
            if product is None:
                continue

            changed = []
            for field in CONTENT_FIELDS:
                value = (fields.get(field) or "").strip()
                if not value:
                    continue
                current = (getattr(product, field, "") or "").strip()
                if current and not overwrite:
                    continue
                if current == value:
                    continue
                setattr(product, field, value)
                changed.append(field)

            if changed:
                to_save.append((product, changed))
                updated += 1
            else:
                skipped += 1

        if dry_run:
            for product, changed in to_save:
                self.stdout.write(f"  would update {product.slug}: {', '.join(changed)}")
        else:
            with transaction.atomic():
                for product, changed in to_save:
                    product.save(update_fields=changed)

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}workspace={workspace.slug} updated={updated} "
                f"unchanged={skipped} not-in-catalogue={len(missing)} "
                f"no-copy-supplied={len(untouched)}"
            )
        )
        if missing:
            self.stdout.write(self.style.WARNING(f"  slugs in JSON with no product: {missing}"))
        if untouched:
            self.stdout.write(self.style.WARNING(f"  products with no copy supplied: {untouched}"))

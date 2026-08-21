# -*- coding: utf-8 -*-
"""
Import product prices from JSON into a workspace, matched by slug.

Catalogues migrated from a legacy system often arrive with placeholder pricing. Unlike
`import_product_content`, this command *always* overwrites — a wrong price is worse than no
price — so it prints a full before/after table and requires `--confirm` to write.

Usage:
    python manage.py import_product_prices <path-to-json> --workspace=<slug_or_id> [--confirm]

JSON shape:
    {"<product-slug>": {"price": "8.50", "rationale": "..."}, ...}
"""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.common.models import Workspace
from bfg.shop.models import Product


class Command(BaseCommand):
    help = "Import product prices from JSON, matched by slug (always overwrites)"

    def add_arguments(self, parser):
        parser.add_argument("prices_path", type=str, help="Path to price JSON")
        parser.add_argument(
            "--workspace",
            type=str,
            required=True,
            help="Workspace slug or numeric id",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually write. Without it the command only reports the diff.",
        )

    def handle(self, *args, **options):
        prices_path = Path(options["prices_path"]).resolve()
        if not prices_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {prices_path}"))
            return
        try:
            with open(prices_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
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

        # Tenant-scoped default manager resolves the workspace from request middleware,
        # which does not exist here; the explicit filter below is the tenant boundary.
        products = {p.slug: p for p in Product.all_objects.filter(workspace=workspace)}

        changes = []
        unchanged = 0
        invalid = []
        for slug, entry in payload.items():
            product = products.get(slug)
            if product is None:
                continue
            try:
                new_price = Decimal(str(entry["price"]))
            except (KeyError, InvalidOperation, TypeError):
                invalid.append(slug)
                continue
            if new_price <= 0:
                invalid.append(slug)
                continue
            if product.price == new_price:
                unchanged += 1
                continue
            changes.append((product, product.price, new_price))

        if invalid:
            self.stdout.write(self.style.ERROR(f"Refusing to run — bad prices for: {invalid}"))
            return

        for product, old_price, new_price in sorted(
            changes, key=lambda c: abs(c[2] - c[1]), reverse=True
        ):
            self.stdout.write(f"  {product.slug[:48]:<50} {old_price:>9} -> {new_price:>8}")

        missing = sorted(set(payload) - set(products))

        if not options["confirm"]:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] would update {len(changes)}, unchanged {unchanged}, "
                    f"not-in-catalogue {len(missing)} — re-run with --confirm to write"
                )
            )
            return

        with transaction.atomic():
            for product, _old, new_price in changes:
                product.price = new_price
                product.save(update_fields=["price"])

        self.stdout.write(
            self.style.SUCCESS(
                f"workspace={workspace.slug} updated={len(changes)} "
                f"unchanged={unchanged} not-in-catalogue={len(missing)}"
            )
        )
        if missing:
            self.stdout.write(self.style.WARNING(f"  slugs with no product: {missing}"))

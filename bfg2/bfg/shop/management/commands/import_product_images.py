# -*- coding: utf-8 -*-
"""
Attach product images from a local directory, matched by slug.

Images are stored as `common.Media` rows and joined to the product through
`common.MediaLink` (the same generic relation `Product.primary_image` reads), so an imported
image behaves exactly like one uploaded through the admin.

Expects a directory containing `<slug>.png` (primary) and optional `<slug>-2.png`,
`<slug>-3.png` … alternates, plus the `manifest.json` written by
`scripts/seo/fetch_product_images.py`. The manifest is optional — files are matched by name.

Non-destructive: a product that already has image links is skipped unless --replace.

Usage:
    python manage.py import_product_images <image-dir> --workspace=<slug_or_id> [--replace] [--dry-run]
"""

from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.common.models import Media, MediaLink, Workspace
from bfg.shop.models import Product

SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def image_files_for(directory: Path, slug: str) -> list[Path]:
    """`<slug>.png` first, then `<slug>-2.png`, `<slug>-3.png`, … in order."""
    found = []
    for suffix in SUFFIXES:
        primary = directory / f"{slug}{suffix}"
        if primary.exists():
            found.append(primary)
            break
    index = 2
    while True:
        matches = [directory / f"{slug}-{index}{s}" for s in SUFFIXES]
        existing = [p for p in matches if p.exists()]
        if not existing:
            break
        found.append(existing[0])
        index += 1
    return found


class Command(BaseCommand):
    help = "Attach product images from a directory of <slug>.png files"

    def add_arguments(self, parser):
        parser.add_argument("image_dir", type=str, help="Directory of <slug>.png files")
        parser.add_argument("--workspace", type=str, required=True, help="Workspace slug or id")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing image links for the product first (default: skip such products)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report without writing")

    def handle(self, *args, **options):
        directory = Path(options["image_dir"]).resolve()
        if not directory.is_dir():
            self.stdout.write(self.style.ERROR(f"Not a directory: {directory}"))
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

        replace = bool(options["replace"])
        dry_run = bool(options["dry_run"])
        product_ct = ContentType.objects.get_for_model(Product)

        products = Product.all_objects.filter(workspace=workspace)
        attached, skipped, no_file = 0, 0, []

        for product in products:
            files = image_files_for(directory, product.slug)
            if not files:
                no_file.append(product.slug)
                continue

            existing = MediaLink.objects.filter(
                content_type=product_ct, object_id=product.id, media__media_type="image"
            )
            if existing.exists() and not replace:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  would attach {len(files)} image(s) to {product.slug}")
                attached += 1
                continue

            with transaction.atomic():
                if replace:
                    # Drop the links and the Media rows they were the only reference to.
                    for link in existing.select_related("media"):
                        media = link.media
                        link.delete()
                        if not media.links.exists():
                            media.delete()

                for position, path in enumerate(files, start=1):
                    media = Media(
                        workspace=workspace,
                        media_type="image",
                        alt_text=product.name[:255],
                    )
                    with open(path, "rb") as fh:
                        media.file.save(path.name, File(fh), save=False)
                    media.save()
                    MediaLink.objects.create(
                        media=media,
                        content_type=product_ct,
                        object_id=product.id,
                        position=position,
                    )
            attached += 1
            self.stdout.write(f"  {product.slug}: {len(files)} image(s)")

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}workspace={workspace.slug} attached={attached} "
                f"skipped-existing={skipped} no-file={len(no_file)}"
            )
        )
        if no_file:
            self.stdout.write(self.style.WARNING(f"  no image supplied for: {no_file}"))

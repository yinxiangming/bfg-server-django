"""Migrate legacy web.Media rows into the unified common.Media model (WI-393).

web.Media is deprecated in favour of common.Media + common.MediaLink. This command
copies each web.Media row into a matching common.Media, preserving the stored file
key (``file.name``) so the underlying file and its URL stay valid.

Idempotent and non-destructive: it never deletes web.Media rows or files, and skips
any row already migrated (matched by workspace + file name). Run --dry-run first.

Usage::

    python manage.py migrate_web_media --dry-run
    python manage.py migrate_web_media
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.common.models.core import Media as CommonMedia
from bfg.web.models import Media as WebMedia


# web.file_type -> common.media_type
_TYPE_MAP = {'image': 'image', 'video': 'video', 'document': 'image'}


class Command(BaseCommand):
    help = "Copy legacy web.Media rows into the unified common.Media model (non-destructive)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Preview only; create nothing.")

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        created = skipped = 0
        for wm in WebMedia.objects.all().iterator():
            key = wm.file.name if wm.file else ''
            if not key:
                skipped += 1
                continue
            already = CommonMedia.objects.filter(workspace_id=wm.workspace_id, file=key).exists()
            if already:
                skipped += 1
                continue
            if dry:
                self.stdout.write(f"[dry-run] would migrate web.Media #{wm.pk} -> {key}")
                created += 1
                continue
            with transaction.atomic():
                cm = CommonMedia(
                    workspace_id=wm.workspace_id,
                    media_type=_TYPE_MAP.get(wm.file_type, 'image'),
                    alt_text=(wm.alt_text or wm.title or '')[:255],
                    width=wm.width,
                    height=wm.height,
                    uploaded_by_id=wm.uploaded_by_id,
                    created_at=wm.uploaded_at,
                )
                cm.file.name = key  # preserve the existing stored key; do not re-upload
                cm.save()
            created += 1
            self.stdout.write(f"migrated web.Media #{wm.pk} -> common.Media #{cm.pk}")
        verb = "would migrate" if dry else "migrated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {created}, skipped {skipped}"))

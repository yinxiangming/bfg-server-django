"""Bulk-copy local MEDIA_ROOT files to the configured S3 bucket (WI-393).

Idempotent and non-destructive: it never deletes local files. The DB stores each
file by its relative ``name`` (key), which is identical on the local filesystem
and on S3, so every Media.url / file.url stays valid after the move — no DB
rewrite is needed.

Sensitive media (Media.is_sensitive) is additionally ensured in the *private*
bucket via bfg.common.storage.private_media_storage().

Usage::

    python manage.py migrate_media_to_s3 --dry-run     # preview, change nothing
    python manage.py migrate_media_to_s3               # upload keys missing on S3
    python manage.py migrate_media_to_s3 --overwrite   # re-upload even if present
    python manage.py migrate_media_to_s3 --verify      # report keys missing on S3

Requires AWS_STORAGE_BUCKET_NAME (S3 active); otherwise the default storage is the
local filesystem and the command is a no-op (reports and exits).
"""
import os

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from bfg.common.models.core import Media
from bfg.common.storage import private_media_storage


class Command(BaseCommand):
    help = "Copy local MEDIA_ROOT files to S3, preserving keys (non-destructive)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Preview only; upload nothing.")
        parser.add_argument('--overwrite', action='store_true', help="Re-upload even if the key already exists.")
        parser.add_argument('--verify', action='store_true', help="Only check that every key exists on S3.")

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        overwrite = opts['overwrite']
        verify = opts['verify']

        if not getattr(settings, 'USE_S3_MEDIA', False):
            self.stdout.write(self.style.WARNING(
                "AWS_STORAGE_BUCKET_NAME is not set — S3 is inactive, default storage is the "
                "local filesystem. Set the env var to migrate. Nothing to do."))
            return

        media_root = settings.MEDIA_ROOT
        if not os.path.isdir(media_root):
            self.stdout.write(self.style.WARNING(f"MEDIA_ROOT does not exist: {media_root}"))
        else:
            self._walk_public(media_root, dry=dry, overwrite=overwrite, verify=verify)

        self._sensitive_pass(dry=dry, overwrite=overwrite, verify=verify)
        self.stdout.write(self.style.SUCCESS("Done."))

    def _walk_public(self, media_root, *, dry, overwrite, verify):
        """Upload every file under MEDIA_ROOT to default (public) S3 storage."""
        uploaded = skipped = missing = 0
        for root, _dirs, files in os.walk(media_root):
            for name in files:
                abs_path = os.path.join(root, name)
                key = os.path.relpath(abs_path, media_root).replace(os.sep, '/')
                exists = default_storage.exists(key)
                if verify:
                    if not exists:
                        missing += 1
                        self.stdout.write(self.style.ERROR(f"MISSING on S3: {key}"))
                    continue
                if exists and not overwrite:
                    skipped += 1
                    continue
                if dry:
                    self.stdout.write(f"[dry-run] would upload {key}")
                    uploaded += 1
                    continue
                with open(abs_path, 'rb') as fh:
                    if exists and overwrite:
                        default_storage.delete(key)
                    default_storage.save(key, File(fh))
                uploaded += 1
                self.stdout.write(f"uploaded {key}")
        if verify:
            self.stdout.write(self.style.SUCCESS(f"verify(public): {missing} missing"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"public: {uploaded} uploaded, {skipped} already present"))

    def _sensitive_pass(self, *, dry, overwrite, verify):
        """Ensure sensitive Media files exist in the private bucket."""
        store = private_media_storage()
        qs = Media.objects.filter(is_sensitive=True).exclude(file='').exclude(file__isnull=True)
        uploaded = skipped = missing = 0
        for media in qs.iterator():
            key = media.file.name
            if not key:
                continue
            exists = store.exists(key)
            if verify:
                if not exists:
                    missing += 1
                    self.stdout.write(self.style.ERROR(f"MISSING private: {key}"))
                continue
            if exists and not overwrite:
                skipped += 1
                continue
            if dry:
                self.stdout.write(f"[dry-run] would put private {key}")
                uploaded += 1
                continue
            # Read from the public/default storage where it currently lives, then
            # write into the private bucket under the same key.
            try:
                with default_storage.open(key, 'rb') as fh:
                    if exists and overwrite:
                        store.delete(key)
                    store.save(key, File(fh))
                uploaded += 1
                self.stdout.write(f"private {key}")
            except FileNotFoundError:
                missing += 1
                self.stdout.write(self.style.ERROR(f"source missing for sensitive {key}"))
        if verify:
            self.stdout.write(self.style.SUCCESS(f"verify(private): {missing} missing"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"private: {uploaded} uploaded, {skipped} already present"))

"""Media storage helpers — public vs private buckets (WI-393).

Public media (avatars, product images, CMS assets) is served from the default
storage: a public-read S3 bucket fronted by a CDN, or the local filesystem in
dev. Sensitive media (package photos, proof-of-delivery, customs documents,
payment proofs) is served from a *private* bucket via short-lived signed URLs so
the objects are never world-readable.

When AWS_STORAGE_BUCKET_NAME is unset (local dev) both helpers resolve to the
same filesystem storage, so sensitive-media code paths behave identically to
public ones and no signing is applied.
"""
from django.conf import settings
from django.core.files.storage import default_storage, storages


def private_media_storage():
    """Storage backend for sensitive media.

    On S3 this is the ``media_private`` alias (private bucket, signed expiring
    URLs); locally it falls back to the same storage as public media so writes
    and reads keep working without AWS.
    """
    if not getattr(settings, 'USE_S3_MEDIA', False):
        return default_storage
    return storages['media_private']


def store_sensitive_file(key, content):
    """Write an uploaded file to the private bucket and return its stored key.

    The returned key is what should be saved on ``Media.file.name`` — it matches
    the layout used by public media so URLs stay consistent across backends.
    """
    return private_media_storage().save(key, content)

# Media storage & S3 (WI-393)

How uploads are stored, how to switch to S3, how sensitive media is kept private,
and how to migrate existing files. No business code changes when switching.

## How storage is selected

`config/settings.py` chooses the backend from one env var:

- **`AWS_STORAGE_BUCKET_NAME` empty** → files are written to `MEDIA_ROOT` on the
  local filesystem and served at `/media/`. This is the dev default.
- **`AWS_STORAGE_BUCKET_NAME` set** → `STORAGES['default']` becomes
  `storages.backends.s3.S3Storage` (public-read, CDN-friendly, unsigned URLs).

A file's DB value is its **relative key** (`file.name`), identical on the local
filesystem and on S3, so URLs stay valid across the switch.

## Unified upload model

All uploads go through **`common.Media` + `common.MediaLink`** (the generic
attachment pattern: `MediaLink` links a `Media` to any object via ContentType).
The PackGo extension's `MediaLinkAttachmentView` (package photos, POD, customs
docs, consolidation, payment proofs) uses this directly.

`web.Media` is **deprecated** — migrate its rows with
`manage.py migrate_web_media` (see below).

## Public vs private (sensitive) media

| | Public media | Sensitive media |
|---|---|---|
| Examples | avatars, product images, CMS assets | package photos, POD, customs docs, payment proofs |
| Storage | `STORAGES['default']` (public bucket + CDN) | `STORAGES['media_private']` (private bucket) |
| URL | unsigned, cacheable | short-lived **signed (SigV4)** URL, expires after `AWS_PRIVATE_URL_EXPIRE` |
| Marked by | `Media.is_sensitive = False` | `Media.is_sensitive = True` |
| Served via | `media_file_url_for_serializer()` | `signed_media_url()` |

Sensitive uploads are written through `bfg.common.storage.private_media_storage()`
and **never** served through the public CDN. Locally (no S3) both resolve to the
same filesystem storage and no signing is applied.

## Environment variables

```bash
AWS_STORAGE_BUCKET_NAME=my-public-bucket      # set → S3 active
AWS_S3_REGION_NAME=ap-southeast-2
AWS_S3_CUSTOM_DOMAIN=cdn.example.com          # optional CloudFront for public media
AWS_ACCESS_KEY_ID=...                         # or use an IAM role
AWS_SECRET_ACCESS_KEY=...
AWS_PRIVATE_STORAGE_BUCKET_NAME=my-private-bucket   # defaults to the public bucket if empty
AWS_PRIVATE_URL_EXPIRE=3600                   # signed-URL TTL, seconds
```

## Bucket / CDN / CORS / lifecycle

- **Public bucket**: block public *ACLs* but allow public *read* via a bucket
  policy (or keep private and serve only through CloudFront with OAC). Front with
  CloudFront and point `AWS_S3_CUSTOM_DOMAIN` at it.
- **Private bucket**: **Block all public access = ON**. No bucket policy granting
  anonymous read. Access is only ever via the signed URLs the app generates.
- **CORS** (both buckets) — allow the frontend origin to GET/PUT:
  ```json
  [{"AllowedOrigins":["https://app.example.com"],
    "AllowedMethods":["GET","PUT","POST"],
    "AllowedHeaders":["*"],"MaxAgeSeconds":3000}]
  ```
- **Lifecycle**: abort incomplete multipart uploads after 7 days; optionally
  transition old objects to Infrequent Access.
- **IAM**: the app principal needs `s3:GetObject`, `s3:PutObject`,
  `s3:DeleteObject`, `s3:ListBucket` on both buckets.

## Migrating existing local files to S3

Non-destructive (never deletes local files); keys are preserved so URLs don't change.

```bash
# 1) point env at the bucket(s), then preview:
python manage.py migrate_media_to_s3 --dry-run
# 2) upload keys missing on S3 (public bucket + sensitive media → private bucket):
python manage.py migrate_media_to_s3
# 3) confirm every key is now present on S3:
python manage.py migrate_media_to_s3 --verify
```

## Migrating legacy web.Media

```bash
python manage.py migrate_web_media --dry-run   # preview
python manage.py migrate_web_media             # copy rows into common.Media
```

Non-destructive: web.Media rows/files are left in place; already-migrated rows are
skipped (matched by workspace + file key).

# Website import contract

This reference describes the current BFG paths used by the website-import
skill. Verify them against the pinned revision before relying on a command or
field.

## Server entry points

- `bfg2/bfg/web/services/site_config_service.py` owns Workspace-scoped site,
  page, menu, content-category, and post upserts.
- `bfg2/bfg/web/management/commands/load_site_config.py` loads configuration
  into an existing Workspace.
- `bfg2/bfg/web/management/commands/bootstrap_workspace_from_site_config.py`
  creates or bootstraps a Workspace and then loads site configuration.
- `bfg2/seed_media/site-config-store.json` is a local example of the
  server's site-config shape, not a customer import bundle.
- `bfg2/bfg/docs/deployment/media-storage-s3.md` documents object storage and
  CDN settings.
- `bfg2/bfg/web/models.py` is the source of truth for Post and media field
  types, including whether a value is a storage key or uploaded file.

## Minimum site-config shape

```json
{
  "site": {"name": "Example site", "description": "..."},
  "theme": {"code": "default", "name": "Default", "primary_color": "#1f2937"},
  "pages": [{"slug": "about", "title": "About", "content": "..."}],
  "menus": [{"slug": "main", "name": "Main", "items": [{"label": "About", "page_slug": "about"}]}],
  "content_categories": [{"slug": "news", "name": "News"}],
  "posts": [{
    "slug": "welcome",
    "title": "Welcome",
    "excerpt": "...",
    "content": "...",
    "category_slug": "news",
    "featured_image": "media/<workspace-id>/example/welcome.jpg",
    "status": "published"
  }]
}
```

The exact accepted fields and status values are defined by the pinned service
and tests. Unknown fields must be rejected or removed during normalization;
do not silently pass arbitrary source JSON into Django models.

## Asset mapping

Use a relative storage key such as
`media/<workspace-id>/<import-name>/<filename>` for model fields that use
Django storage. Resolve the public URL with the configured storage/CDN at
render time, or use a CDN URL only when the target contract explicitly asks
for one. Keep source URLs in the manifest rather than replacing provenance in
the CMS record.

---
name: bfg-website-import
description: Import an existing public website into a BFG Workspace as reusable site configuration, CMS pages/posts, menus, and reviewed extension data with CDN-hosted assets. Use when migrating a Wix, WordPress, static, or other public site into BFG, generating site-config, or preparing a repeatable website import.
disable-model-invocation: false
metadata:
  short-description: Import an existing public website into BFG safely
---

# BFG Website Import

Use this project skill when an existing public website needs to become a
Workspace-scoped BFG site. The result must be reviewable, repeatable, and safe
to run again. Keep customer-specific source data in a separate import bundle;
do not turn one brand's content into a generic extension or server fixture.

## Required input

Before extracting or writing data, record:

- public source URL and any allowed sitemap or feed URLs;
- target environment and Workspace slug or id;
- the staff or admin user that should own imported posts;
- content scope: pages, menus, posts/news, events, members, categories, and
  other extension resources;
- asset storage/CDN prefix and whether the source owner approved asset reuse;
- merge or replace intent. Default to a workspace-scoped merge. Treat replace
  as a destructive operation and require explicit confirmation.

If the source, target Workspace, or asset ownership is unclear, stop before
writing. Never use credentials, paywalled pages, login bypasses, or private
user data as an import source.

## Safety invariants

- Read only public pages, robots rules, sitemaps, feeds, and explicitly
  approved assets. Respect rate limits and source terms.
- Preserve the source URL, retrieval timestamp, extractor version, and any
  manual review notes in the import bundle.
- Resolve the target Workspace once, then scope every category, post, menu,
  page, and extension write to that Workspace. Never infer tenancy from a
  browser header or an untrusted source field.
- Do not invent event dates, member consent, prices, authorship, or operational
  records. Public team listings are review data, not automatic MemberProfile
  creation.
- Keep credentials and provider tokens out of JSON, logs, commits, tickets,
  and generated reports. Do not log full scraped HTML when it may contain
  personal information.
- Use stable ASCII slugs, sanitized HTML, bounded content length, and explicit
  source-to-target mappings. Remove navigation/footer boilerplate without
  losing source attribution.
- Do not delete a database, reset migrations, or replace an existing Workspace
  as part of this skill. A failed import must be recoverable by rerunning the
  bundle after fixing the source or mapping.

## Import bundle

Create a project or brand-owned bundle outside reusable server code. At
minimum include:

```text
import-bundle/
  README.md
  site-config.json
  assets-manifest.json
  community-data.json        # only when a community extension is in scope
  source/                    # optional raw snapshots, never credentials
```

The `site-config.json` follows the server's site-config contract and may
contain `workspace_bootstrap`, `site`, `theme`, `pages`, `menus`,
`content_categories`, and `posts`. Keep community records in
`community-data.json` when they require extension-specific review or fields.
See [references/import-contract.md](references/import-contract.md).

For each page or post, retain a source URL and use a deterministic slug. Map
source categories to BFG content categories before creating posts. Use the
workspace's configured default author unless the source provides an approved,
stable author mapping.

## Extraction and normalization

1. Fetch the homepage, robots file, sitemap, and explicitly approved linked
   content. Build a URL inventory before downloading large assets.
2. Classify each URL as a page, menu target, post/news item, event, member
   entry, category, asset, or unsupported/private route.
3. Normalize titles, summaries, body HTML, dates, language, canonical URLs,
   and image references. Sanitize HTML and reject scripts, forms, tracking
   pixels, and unsafe embeds unless the target contract explicitly supports
   them.
4. Deduplicate by canonical URL and then by stable slug within the target
   Workspace. Keep a mapping report for skipped, merged, and manually
   reviewed records.
5. Generate the import bundle and validate its JSON before touching BFG.

Use a site-specific extractor under the importing project's scripts or docs;
do not add a brand's scraper or content to this reusable skill.

## Assets and CDN

Download approved assets once, hash them, and write an `assets-manifest.json`
with `source_url`, `storage_key`, `cdn_key`, `cdn_url`, `sha256`, content type,
and byte size. Store relative media paths in BFG fields where the model expects
a storage key; use the public CDN URL only in fields that explicitly require a
URL.

Use the environment's configured object storage and CDN settings, normally
`AWS_STORAGE_BUCKET_NAME`, `AWS_LOCATION`, `AWS_S3_CUSTOM_DOMAIN`, and
`MEDIA_PUBLIC_BASE_URL`. A recommended key shape is:

```text
nexus/<environment>/media/<workspace-id>/<brand-or-import-name>/<filename>
```

Do not commit downloaded binaries. Upload with the storage provider's CLI or
approved server path, set the correct content type and cache policy, then
verify the expected object count, hashes for sampled objects, and HTTP `HEAD`
responses from the CDN. Record the exact prefix in the import README.

## BFG import

Read the pinned server revision before running commands. For a new Workspace,
use the bootstrap command; for an existing Workspace, use the scoped loader:

```bash
python manage.py bootstrap_workspace_from_site_config <path>/site-config.json --user=<staff-id>
python manage.py load_site_config <path>/site-config.json --workspace=<slug-or-id> --user=<staff-id>
```

Use the default merge behavior. Only pass a replace option after the user has
approved the exact affected Workspace and the bundle has been backed up. Load
extension-specific community data through that extension's documented command
or service, not through an unreviewed generic proxy.

## Verification

Run checks in this order:

1. Parse and schema-check every bundle file; confirm all referenced assets are
   present in the manifest.
2. Run `python manage.py check` and the focused site-config/import tests.
3. Run migration drift checks if models or extension migrations changed.
4. Query counts by Workspace for pages, categories, posts, menus, and any
   extension records. Confirm no records were written to another Workspace.
5. Check representative CDN URLs and render the public homepage, menu targets,
   post detail pages, and extension pages. Confirm empty collections use an
   empty state rather than a misleading 404 when the route is valid.
6. Rerun the import and confirm it is idempotent: no duplicate slugs,
   categories, posts, or assets are created.

Report the source and target, bundle files, imported counts, skipped/manual
review items, CDN prefix, exact tests, and any remote upload or deployment
steps that were not performed. Do not claim a UAT or Production deployment
from local import evidence alone.


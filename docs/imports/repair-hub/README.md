# Repair Hub website import bundle

Prepared from the public pages, sitemap, and JSON endpoints of
`https://therepairhub.co.nz/` on 2026-09-20 using the `bfg-website-import`
skill. This is a reviewable Workspace-scoped import for a mobility-access
repair and parts business, not a generic server fixture.

## Contents

- `site-config.json` — site metadata, pages, navigation, categories, and
  public project/service/product records represented as CMS posts.
- `assets-manifest.json` — source URLs, checksums, storage keys, and planned
  CDN URLs for 12 public images.
- No `community-data.json`: the source exposes no public member records.

The public sitemap exposed home, projects, products, services, about, contact,
FAQ, testimonials, and detail routes. Public APIs exposed three projects,
three products, four services, navigation, settings, and categories. The blog
endpoint required authentication and was not imported. The settings endpoint
contained provider credentials; those fields were discarded and must never be
copied into an import bundle.

Some source SEO metadata is inconsistent (for example, legacy descriptions
mention television repair). It is retained only as source-derived content and
must receive editorial review. No dates, customers, testimonials, or other
operational records were invented.

## Assets and import

Images were downloaded to temporary staging for hashing only; no binaries are
committed. Storage keys use `media/<workspace-id>/repair-hub/<filename>`.
CDN upload was not performed because no approved target Workspace or storage
credentials were provided. Replace placeholders in the manifest before
uploading and verify object count, sampled hashes, and CDN `HEAD` responses.

```sh
python manage.py bootstrap_workspace_from_site_config \
  docs/imports/repair-hub/site-config.json --user=<staff-user-id>
```

For an existing Workspace use the scoped loader with default merge mode. Do
not use replace mode without explicit approval and a backup. After import,
render the homepage, navigation targets, and project/service/product details,
then rerun the import to confirm idempotency.

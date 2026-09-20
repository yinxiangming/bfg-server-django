# Ultimate Space Design import bundle

Source: https://ultimatespacedesign.co.nz/projects
Target: a new BFG Workspace for an architecture, interiors, and window-treatment studio.
Retrieved: 2026-09-20
Extractor: public JSON endpoints (`/api/projects`, `/api/services`, `/api/products`, `/api/navigation-modules`) and the public Projects page.

## Scope

This bundle contains public navigation, studio pages, project records, project categories, and SEO metadata. Project descriptions and locations are copied from the public Projects response and lightly normalized for HTML. No private staff, customer, login, or contact-form data is included.

The project API currently exposes ten projects. Three projects are categorized as Commercial by the source; the other seven have no source category and remain in `projects` for editorial review. No project date or category has been invented.

## Assets

`assets-manifest.json` lists the public project image URLs and the homepage hero URLs. The CDN fields are deliberately `null` and `status` is `not_uploaded`: this local task did not upload source-owned assets to object storage. Before import, obtain reuse approval, upload to an environment-specific prefix such as `nexus/<environment>/media/<workspace-id>/atelier-grid/`, then replace the storage and CDN fields and verify sampled `HEAD` responses. Downloaded binaries are intentionally not committed.

## Import

Review and edit `site`/`workspace_bootstrap` before use. For a new Workspace:

```bash
python manage.py bootstrap_workspace_from_site_config docs/imports/ultimate-space/site-config.json --user=<staff-id>
```

For an existing Workspace, use the scoped merge loader:

```bash
python manage.py load_site_config docs/imports/ultimate-space/site-config.json --workspace=<workspace-id-or-slug> --user=<staff-id>
```

The bundle is content-only and does not activate an extension or assign a skin. Activate the `atelier-grid` skin through the extension's documented provisioning flow after reviewing the branding and asset mapping. Do not use replace mode without explicit Workspace-scoped approval and a backup.

## Review notes

- Source brand name is retained in the customer-owned bundle, not in the reusable skin name.
- The source contains operational API settings; those were intentionally excluded, including credentials.
- Image reuse, copyright, and final copy require owner review before public publication.
- CDN upload, BFG import, Workspace creation, and deployment were not performed here.

# Branding architecture

Branding is a reusable BFG extension for public portal configuration, email-first
registration, tenant provisioning, and one-time tenant sign-in. The stable Django
app and web plugin ID is `brand_portal`.

## Source ownership

- `server/` owns models, migrations, services, permissions, and API routes.
- `client/plugins/brand_portal/` owns the administrative configuration UI.
- `server/tests/` verifies registration, provisioning, authorization, and isolation.
- `docs/` owns reusable contracts and integration guidance.

The backend is mounted through the bundled `apps/brand_portal` relative link.
It remains subject to `LOCAL_APPS` and per-workspace extension activation.
Independent frontend hosts consume the client plugin through their extension
linker or build materializer. Dependencies and generated output are not source.

## Configuration boundaries

A brand workspace configures permitted tenant extensions, theme, locale, and
its Cluster relationship. No particular business plugin is required. Cluster
routing, user membership, email delivery, and SSO are shared BFG host services.
Marketing content, logos, customer-specific defaults, callback origins, and
infrastructure addresses belong to each deploying host and its workspace data.

A branding website uses a narrow server-side BFF and workspace-scoped credentials.
The browser does not receive backend credentials or choose tenant defaults.
Registration verifies email before setup; provisioning creates durable owner
membership and approved extension activation. SSO is single-use, rechecks access,
and never places a reusable access token in a redirect URL.

Local HTTP requires explicit development configuration and local hostname
validation. Production callback origins and tenant redirects require HTTPS.
See `bff.md` for the public integration contract and the BFG Cluster setup skill
for routing and provisioning verification.

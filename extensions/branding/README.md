# Branding extension

This reusable extension is bundled in BFG Server. Its runtime ID remains
`brand_portal`; source relocation does not rename Django apps, API paths, or migrations.

- Backend: `server/`, mounted through `apps/brand_portal`.
- Tests: `server/tests/`, discovered by Django.
- Documentation: `docs/`.
- Web plugin: `client/plugins/brand_portal/`, mounted by the frontend host.

A standalone BFG checkout includes the relative backend entrypoint link.
Automatic local-app discovery finds it when `LOCAL_APPS` is unset. With an
explicit `LOCAL_APPS` list, include `brand_portal` to load the module. Workspace
activation and permissions still govern its available features.

Run focused tests with `DJANGO_SETTINGS_MODULE=config.test` and the intended
`LOCAL_APPS` list. The test database must be isolated from deployed data.
Client dependencies and build output remain untracked; production deployment
values, business extension defaults, and brand assets belong to the host.

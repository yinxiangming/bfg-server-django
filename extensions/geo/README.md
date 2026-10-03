# Geo extension

This reusable extension is bundled in BFG Server. Its runtime ID remains
`geo`; source relocation does not rename Django apps, API paths, or migrations.

- Backend: `server/`, mounted through `apps/geo`.
- Tests: `server/tests/`, discovered by Django.
- Documentation: `docs/`.

A standalone BFG checkout includes the relative backend entrypoint link.
Automatic local-app discovery finds it when `LOCAL_APPS` is unset. With an
explicit `LOCAL_APPS` list, include `geo` to load the module. Workspace
activation and permissions still govern its available features.

Run focused tests with `DJANGO_SETTINGS_MODULE=config.test` and the intended
`LOCAL_APPS` list. The test database must be isolated from deployed data.
Client dependencies and build output remain untracked; production deployment
values, business extension defaults, and brand assets belong to the host.

# Nexus stack and extensions (server + client)

This note describes how the **Nexus** monorepo arranges the **Django BFG** server and **Next.js** client around **extensions/plugins**. Paths are relative to the Nexus repository root unless stated otherwise.

## Core principles for agents

1. **Prefer extensions** — Add features as `extensions/<name>-client` and `extensions/<name>-server` (or scaffolded apps) instead of editing `bfg2` core unless the user explicitly asks to change framework code.
2. **Respect multi-tenancy** — All tenant data is workspace-scoped (`Workspace`, `WorkspaceMiddleware`, headers / domain resolution).
3. **Reuse BFG modules** — Use `bfg.common`, `bfg.shop`, `bfg.web`, etc., before inventing parallel models.

## Server (Django BFG)

| Location | Role |
|----------|------|
| `src/server/bfg2/bfg/` | Framework packages: `core`, `common`, `web`, `shop`, `delivery`, `marketing`, `finance`, `support`, `inbox`, `platform`, … |
| `src/server/apps/` | Local Django apps (each needs `apps.py` + `urls.py` for auto-discovery). |
| `src/server/config/local_apps.py` | Discovers packages under `apps/` and mounts them at `/api/v1/<app_name>/`. |

## Client (Next.js, App Router)

| Location | Role |
|----------|------|
| `src/client/src/app/` | Routes: `(storefront)/`, `admin/`, `account/`, `auth/`, … |
| `src/client/src/plugins/` | Symlinked or copied extension frontends. |
| `src/client/src/extensions/` | Plugin registry and extension runtime (`registry.ts`, `context.tsx`, …). |

## Frontend extension flow

1. Sources live under `extensions/<name>-client/` and are linked into `src/client/src/plugins/<name>/` (see repo `scripts/link-nexus-extensions.sh`).
2. **Turbopack:** each extension directory should have a `node_modules` symlink pointing at the root client `node_modules` so shared packages resolve consistently.
3. Each extension exports an **`Extension`** object that can:
   - **Navigation** — `adminNav` / `accountNav` with `position`: `before` | `after` | `replace` | `hide`.
   - **Slots** — `sections` / `slots` targeting a `page` and `targetSlot` (prefer `targetSlot`; `targetSection` is legacy).
   - **Data hooks** — `dataHooks` with `onLoad` / `onSave` for API interception.

## Backend extension flow

1. Sources live under `extensions/<name>-server/` and are linked into `src/server/apps/<name>/`.
2. HTTP API is mounted at `/api/v1/<name>/` via `local_apps` discovery.

**Deploy note:** `apps/*` may be gitignored in some server templates; vendored or synced copies are required for Docker/Dokku images if extensions must exist in production (see deployment docs for your fork).

## Setup commands (Nexus)

- Scaffold app: `bash src/server/bootstrap/bootstrap-app.sh`
- Link extensions: `bash scripts/link-nexus-extensions.sh` (from repo root)
- Client code generation: `npm run prepare` in `src/client` (plugin loaders, routes, theme registry)
- Backend dev: `make init`, `make install-bfg2` (see server `README.md` / `CLAUDE.md`)

## Further reading

- Schema-driven UI (lists/forms): [reference/schema-driven-ui-admin.md](../reference/schema-driven-ui-admin.md)
- Embedded platform env: [deployment/embedded-platform-environment.md](../deployment/embedded-platform-environment.md)
- Models & REST reference: [reference/models-and-api.md](../reference/models-and-api.md)

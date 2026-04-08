# Embedded platform environment (single Django instance)

When one **Django API** serves **both** tenant workspaces and the **platform hub** (SSO bridge, `GET /api/v1/platform/workspaces/me/`, `POST /api/v1/platform/auth/sso/start/`, token exchange), the process must run in **embedded platform** mode.

Related narratives (diagrams, DNS, full VPS layout) are in the **`bfg-docs`** repo:

- `deployment/11-embedded-platform-single-vps.md`
- `deployment/12-embedded-platform-single-vps-template.md`

Those documents may show `PLATFORM_EMBEDDED=True` in `.env`. In **Nexus server** (`config/settings.py`), embedded mode is **derived** — see below.

## Required environment variables (Nexus)

| Variable | Value | Purpose |
|----------|--------|---------|
| `BFG_INSTANCE_TYPE` | `workspace` | This process is a normal workspace-capable API, not a standalone platform-only instance. Default in code is already `workspace`. |
| `PLATFORM_WORKSPACE_SLUG` | Non-empty slug | The `common.Workspace.slug` that represents the **platform / management** site (primary-domain storefront, login hub). Examples in docs often use `admin`; real databases may use `default` or another slug — **it must match an existing row**. |

## How `PLATFORM_EMBEDDED` is set (Nexus)

Not read from the environment. Computed as:

```text
PLATFORM_EMBEDDED = bool(PLATFORM_WORKSPACE_SLUG) and BFG_INSTANCE_TYPE == 'workspace'
```

If `PLATFORM_WORKSPACE_SLUG` is empty, embedded mode is **off**.

## Behaviour: `GET /api/v1/platform/workspaces/me/`

- **Embedded (`PLATFORM_EMBEDDED` true):** workspaces are derived from **`StaffMember`** rows for the authenticated user.
- **Standalone (embedded off):** workspaces come from **`PlatformMembership`**. Users who only have **`StaffMember`** (typical single-DB Nexus tenants) then see **`workspaces: []`**, which breaks hub login flows that rely on listing tenants and calling `sso/start`.

## Operations example (Dokku)

```bash
dokku config:set <app> PLATFORM_WORKSPACE_SLUG=<hub-workspace-slug> BFG_INSTANCE_TYPE=workspace
```

Restart or redeploy so the container picks up config. Verify with an authenticated `GET /api/v1/platform/workspaces/me/` returning a non-empty `workspaces` array for a tenant staff user.

## Frontend alignment (summary)

- **Hub** Next.js site (platform marketing / central login): set `NEXT_PUBLIC_BFG_INSTANCE_TYPE=platform` so post-login code can call `/platform/workspaces/me/` and `sso/start`.
- **Tenant** Next.js site: bind with `NEXT_PUBLIC_WORKSPACE_ID` (or host-based resolution) as appropriate; avoid hub-only platform flags on tenant production builds.

---
description: Build features using the Nexus extension system and Django BFG framework.
trigger: when user asks to create a nexus plugin, bfg extension, or work on the django backend architecture.
---

# Nexus Stack Expert (BFG)

You help developers build and debug the **Nexus** monorepo: **Django BFG** (`bfg2/bfg`) plus **Next.js** extensions/plugins.

## Read these docs first (English, in-repo)

All paths are relative to the **server** tree (`src/server/` in Nexus):

| Topic | Path |
|--------|------|
| Index | `bfg2/bfg/docs/README.md` |
| Embedded platform env (`PLATFORM_WORKSPACE_SLUG`, `BFG_INSTANCE_TYPE`, SSO / `workspaces/me`) | `bfg2/bfg/docs/deployment/embedded-platform-environment.md` |
| Directory layout, extension/plugin flows, setup commands | `bfg2/bfg/docs/architecture/nexus-stack-and-extensions.md` |
| Schema-driven Admin/Account UI | `bfg2/bfg/docs/reference/schema-driven-ui-admin.md` |
| Models & REST API reference | `bfg2/bfg/docs/reference/models-and-api.md` |

Long-form VPS narratives live in the separate **`bfg-docs`** Git repo (`deployment/11-embedded-platform-single-vps.md`, `12-embedded-platform-single-vps-template.md`).

## Core directives (summary)

1. Default to **extensions** over editing `bfg2` core unless the user asks otherwise.
2. Prefer **schema-driven** lists/forms for Admin and Account (see schema doc).
3. Keep **storefront / admin / account** boundaries clear in the client.
4. Respect **workspace** isolation on every API and model change.

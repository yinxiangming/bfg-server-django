---
name: bfg-server-extension-implement
description: Implements or integrates a contract-defined BFG extension on the Django Server host while preserving Workspace isolation and extension ownership.
---

# BFG Server extension implementation

Use this project-level skill when an extension repository supplies a versioned
contract and needs Server models, migrations, APIs, permissions, activation,
email events, or generic host support.

## Required input

Before editing, require:

- extension repository path and extension id;
- versioned contract path;
- exact Server baseline revision;
- dispatch result path inside the extension repository.

Stop and report a precise blocker if the contract or baseline is missing. Do
not infer a production API from a brand-site environment.

## Ownership decision

Inspect the pinned host before choosing an implementation shape.

- Domain models, serializers, permissions, routes, migrations, fixtures, and
  tests belong to the extension Server package.
- Keep a unified extension layout when the extension has more than one
  surface: `extensions/<short-name>/server/` for Django code and migrations,
  `client/plugins/<plugin-id>/` for a host web plugin, optional
  `client/miniapp/` for a mini-program, and optional `skins/` for
  extension-owned storefront themes, `docs/` for contracts and operations,
  `tests/` for focused non-colocated tests, and `e2e/` for host or service
  end-to-end tests. Each directory remains extension-owned; do not move its
  policy into a generic host package.
- Generic manifest loading, activation gates, Workspace primitives, audit,
  email delivery, and extension-host utilities belong to BFG Server.
- A host adapter must stay thin and must not copy extension policy.

The root `extension.json` is the stable manifest. In a Nexus host, map it in
`extensions/registry.json` to the stable Django app name and client plugin
entrypoint. The folder name may be short (`branding`, `resale`, `channels`),
but it must not silently rename an existing app, migration namespace, API
route, or plugin id. Host links under `src/server/apps/` and
`src/client/src/plugins/` should be rebuildable relative links to the unified
extension tree. A server-only extension may omit the client entrypoint, and a
client-only extension may omit `server/`; keep the same manifest and ownership
rules.

Record every host-owned change in the dispatch result with the reason it could
not remain extension-owned.

## Safety invariants

- Resolve the Workspace before object lookup and constrain every queryset and
  write to it. Cross-Workspace public discovery must use an explicit, reviewed
  scope rather than ambient tenant state.
- Do not treat `X-Workspace-ID` as authenticated production identity. Follow
  the host's current JWT/API-key and middleware contract.
- Define anonymous, member, staff, and administrator access for every route.
- Use atomic transactions for capacity, sequence, balance, or idempotency
  rules. Add collision and retry tests.
- Public errors use stable codes and fixed messages; never serialize exception
  text.
- Activation is fail-closed when the extension is unavailable or disabled.
- Migrations are forward-safe and tested on a clean database. Never reset or
  delete a database as part of this skill.

## Implementation flow

1. Verify `HEAD` equals the requested baseline and the worktree is clean.
2. Inspect existing local-app discovery, `ExtensionManifest`, activation
   permissions, URL conventions, tenant managers, and comparable extensions.
3. Map each contract resource and permission to extension-owned code or a
   documented generic-host gap.
4. Implement the smallest generic host change and extension package needed by
   the contract.
5. Add model, serializer, service, route, permission, migration, activation,
   and email tests in proportion to the implemented behavior.
6. Run focused tests first, then the relevant Server suite and migration drift
   check.
7. Write the dispatch result. Do not push, merge, seed remote data, or deploy
   without explicit authorization.

## Required tests

For every scoped resource include positive and negative tests for:

- same-Workspace access and cross-Workspace IDOR attempts;
- anonymous/member/staff/admin permissions;
- extension disabled and missing prerequisites;
- invalid lifecycle transitions and stable public errors;
- duplicate/idempotent writes and relevant concurrency boundaries;
- clean migration application and no unintended migration drift.

## Dispatch result

Write JSON at the requested extension-repository path containing:

- `status`: `complete`, `blocked`, or `failed`;
- Server baseline and resulting commit/worktree revision;
- contract version and extension id;
- extension-owned files and host-owned files changed;
- migrations and API routes added;
- tests executed with exact results;
- compatibility notes, blockers, and unperformed remote actions.

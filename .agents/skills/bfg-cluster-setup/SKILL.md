---
name: bfg-cluster-setup
description: Plan, configure, migrate, or validate BFG Cluster records and their Workspace domain routing. Use when adding a brand-specific Workspace domain root, assigning WorkspacePlatformProfile.cluster, or preparing a genuinely independent BFG infrastructure cluster.
metadata:
  short-description: Configure BFG clusters and workspace routing
---

# BFG Cluster Setup

Set up BFG clusters without confusing a database routing record with deployed
infrastructure. Preserve existing Workspace routing and keep UAT and Production
as separate release gates.

## Start with the mode

Classify the requested cluster before changing anything:

- **Logical brand-routing cluster:** shares an existing API, database, Redis,
  object storage, and Workspace frontend deployment, but uses a different
  `frontend_base_url` so newly provisioned Workspaces receive a brand-specific
  system domain.
- **Physical infrastructure cluster:** has independently deployed API, database,
  Redis, object storage, secrets, migrations, monitoring, and frontend routing.

A `Cluster` row never deploys infrastructure. If the user asks for a physical
cluster, prepare and verify the infrastructure before enabling Workspace
assignment.

## Read the implementation before acting

Inspect these files in the target revision because downstream projects may pin
different BFG commits:

- `bfg2/bfg/platform/models/cluster.py`
- `bfg2/bfg/platform/models/workspace_profile.py`
- `bfg2/bfg/common/models/workspace_domain.py`
- `bfg2/bfg/common/services/workspace_service.py`
- `bfg2/bfg/platform/signals.py`

If a Brand Portal is involved, also inspect its profile and provisioning
service. The portal's Workspace cluster determines the target cluster for newly
created Workspaces; the portal profile, not the Cluster, determines which
extensions and defaults are installed.

## Preserve these invariants

- Treat `Cluster.id` as a stable identifier. Do not rename it after Workspaces
  are assigned.
- Set `frontend_base_url` to the HTTPS root used to derive system domains, for
  example `https://uat.example.com`. Do not include a wildcard, Workspace slug,
  path, query, or trailing slash.
- Expect a Workspace with slug `shop-a` to receive
  `shop-a.uat.example.com`.
- Audit every `WorkspacePlatformProfile` bound to an existing Cluster before
  editing its `frontend_base_url`. Saving that Cluster regenerates the system
  domain for every bound Workspace.
- Do not use `QuerySet.update()` for ordinary cluster assignment because it
  bypasses model signals. If a controlled migration requires it, explicitly
  reconcile `WorkspaceDomain` rows and invalidate domain caches.
- Provision wildcard DNS and TLS before assigning real Workspaces.
- Keep API credentials, database credentials, Redis credentials, and provider
  tokens out of commits, commands, tickets, and logs.
- Do not apply a UAT configuration to Production without a separate approval
  and Production validation.

## Workflow

1. Inventory the target environment, existing Clusters, bound Workspaces,
   system domains, DNS ownership, TLS status, and frontend project.
2. Record whether the change is logical routing or physical infrastructure.
3. Define the Cluster fields, domain root, capacity policy, rollback target,
   and affected Workspaces.
4. For a physical cluster, deploy and validate all infrastructure first.
5. Create the Cluster while no customer Workspace is assigned to it.
6. Configure wildcard DNS and TLS on the Workspace frontend deployment.
7. Bind the intended management or Brand Portal Workspace through
   `WorkspacePlatformProfile.cluster`.
8. Configure Brand Portal defaults and a dedicated BFF API key separately when
   applicable.
   A direct generic workspace create/provision request may pass a core ``skin``.
   Brand Portal provisioning should use its ``default_theme`` setting instead;
   an extension-owned theme is valid only when that extension is also listed in
   ``provisioning_extensions``.
9. Validate database state, DNS, TLS, Workspace creation, system-domain
   materialization, extension activation, and SSO.
10. Record evidence and stop at the requested environment boundary.

Read [references/cluster-runbook.md](references/cluster-runbook.md) for the
field matrix, preflight queries, logical and physical checklists, validation,
rollback, and current implementation limitations.

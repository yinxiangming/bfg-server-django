---
name: bfg-cluster-setup
description: Audit, configure, or validate BFG Cluster routing and Brand Portal tenant registration. Use for WorkspacePlatformProfile.cluster assignment, brand-specific tenant domains, Cluster health/capacity controls, or planning an independent deployment.
metadata:
  short-description: Configure clusters and branded tenant registration
---

# BFG Cluster Setup

Produce a verified Cluster and tenant-routing plan for the requested environment.
A Cluster record describes routing and resources; it does not deploy servers or
switch Django database connections.

## Choose the mode

- **Logical brand routing:** one existing BFG API/database/frontend deployment,
  with a separate tenant domain root for a brand.
- **Physical infrastructure:** independently deployed API, database, Redis,
  storage and frontend. Verify those resources before enabling assignments;
  the current registration service is not a remote deployment provisioner.

For a branded registration site, read
[references/brand-portal-registration.md](references/brand-portal-registration.md).
For fields, control APIs, domain changes, health and rollback, read
[references/cluster-runbook.md](references/cluster-runbook.md).

## Establish the actual state

1. Identify the Server checkout/revision, environment, database, frontend
   deployment and intended Brand Workspace. Do not infer live configuration
   from a website name, documentation, a sample env file or a health response.
2. Inspect the pinned core: `bfg2/bfg/platform/models/{cluster,workspace_profile}.py`,
   `bfg2/bfg/platform/views/control_views.py`,
   `bfg2/bfg/common/services/workspace_service.py`,
   `bfg2/bfg/common/models/workspace_domain.py`, and platform signals.
   Find the hosting project's Brand Portal extension separately; it is not
   guaranteed to ship in this Server repository.
3. Run the read-only inventory from the Server root using its configured Python:

   ```sh
   python manage.py shell -c "exec(open('.agents/skills/bfg-cluster-setup/scripts/inspect_clusters.py').read())"
   ```

   The script queries only the configured database, reports missing tables/apps,
   and omits credentials, tokens and customer identities. An empty inventory is
   evidence of missing configuration, not authorization to create sample rows.
4. Compare migration state with the actual schema before any schema repair.
   Back up the target before writes. Do not reset a database, fake migrations,
   delete files, or bulk reassign existing tenants to make an empty screen look
   populated.

## Configure within the authorized scope

- Record stable Cluster ID, infrastructure versus routing mode, API origin,
  tenant domain root, capacity, affected profiles, and rollback mapping.
- Configure wildcard DNS/TLS on the tenant frontend, not only the marketing
  website. Public tenant URLs currently resolve to HTTPS; a loopback URL with
  a dev-server port is not a working end-to-end domain setup.
- Prefer the superuser-only control API for audited Cluster changes. It requires
  confirmation, a change reason and `X-Idempotency-Key`; updates additionally
  require the version read from the current record.
- Bind only the intended Brand Workspace through a saved
  `WorkspacePlatformProfile`. New Brand Portal tenants inherit that Cluster;
  existing tenants are not moved by changing the Brand Workspace's binding.
- Configure Brand Portal registration/defaults/extensions and dedicated
  server-only BFF credentials separately. Region alone does not select a Cluster.
- Inventory all bound profiles before changing a Cluster's frontend root:
  save signals regenerate their system domains and may replace old domain rows.

## Verify and report

For independent infrastructure, verify database identity, migration state, an
authorized read/write canary and backup restore separately from HTTP liveness.
Verify stored assignment and system domains, frontend host routing, TLS/CORS,
protected Cluster reads, brand config, an authorized disposable registration,
extension activation, and one-time SSO. Include a non-superuser denial check.
Do not send registration emails or perform remote writes for a read-only audit.
Keep existing task authorization; only resolve genuinely missing write scope.

Report the configured environment/revision, mode, affected profiles, checks
performed, unresolved gaps and rollback artifact. Separate a configured record,
a reachable service, and a completed registration flow. Keep deployment-specific
hosts, test accounts and transient incidents out of this reusable skill.

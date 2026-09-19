# Platform control-plane implementation tree

**Status:** In progress  
**Boundary:** Django `is_superuser` only  
**Owner console:** `/api/v1/platform/console/` remains unchanged

This is the execution tree for operating a multi-workspace Platform without
turning an ordinary workspace owner into a deployment administrator.

## P0: Access and evidence

- [x] Expose `/api/v1/platform/control/` separately from the owner console.
- [x] Require authenticated Django superusers on every control route.
- [x] Keep authenticated non-superusers on a safe, uniform 403 response.
- [x] Require `confirm=true`, an operator reason, and an idempotency key for
      sensitive repeatable writes.
- [x] Store append-only audit events with actor, request ID, source IP, reason,
      and redacted before/after snapshots.
- [x] Keep credentials out of API responses, action replays, and audit payloads.

## P1: Workspace lifecycle

- [x] List and inspect all workspaces as a superuser.
- [x] Suspend, resume, schedule deletion, and restore without hard-deleting
      tenant data.
- [x] Show lifecycle operation history without worker exception details.
- [x] Export a configuration-only template; omit members, business data, media,
      and credentials.
- [x] Import a reviewed configuration template with an existing owner and only
      pending custom domains.
- [x] Request an administrator password-reset email through the existing Django
      password-reset path.
- [ ] Add a retention worker that performs a separately approved purge after the
      scheduled deletion date. It must be disabled by default and produce a
      final audit event.
- [ ] Add an explicit migration workflow between clusters. Do not reuse export
      and import as a live-data migration.

## P2: Cluster operations

- [x] List, create, and edit clusters with optimistic configuration versions.
- [x] Refuse capacity below assigned workspaces and prevent inactive clusters
      from accepting new workspaces.
- [x] Add a fixed-path HTTPS health probe, allowlisted by
      `CLUSTER_HEALTH_ALLOWED_HOSTS`, with no redirects, proxy environment, IP
      literals, credentials, or response-body disclosure.
- [ ] Provide a controlled assignment/migration queue with capacity reservation,
      rollback, and progress events.
- [ ] Add a deployment health dashboard based on stored observations, rather
      than browser-side probes.

## P3: Policy, billing, and extensions

- [x] Preserve existing variable, meter-price, exchange-rate, cap, and runtime
      entitlement data models rather than duplicating them.
- [x] Publish strict-superuser control aliases for existing configuration
      endpoints while the client moves from the historical path.
- [ ] Move all privileged configuration reads and writes to dedicated control
      view classes, then retire the historical privileged console aliases.
- [ ] Add audit/idempotency coverage to the legacy configuration services before
      removing their aliases.

## P4: User interface and release verification

- [x] Keep workspace-owner calls on `/console/`.
- [x] Route privileged lifecycle, cluster, audit, and configuration calls to
      `/control/` in the client.
- [x] Build the client and run focused server regression tests locally.
- [ ] UAT smoke test with a real Django superuser: workspace list, Cluster list,
      audit read, and a non-destructive health-probe configuration refusal.
- [ ] UAT smoke test with a real ordinary owner: existing Workspace management
      works, but every `/control/` endpoint returns 403.
- [ ] Run and verify database migrations from the current deployment schema.
- [ ] Promote only as part of the agreed larger production release.

## Non-goals

- No hard delete from a browser action.
- No browser-visible Cluster connection credentials.
- No arbitrary URL health probes or browser-driven infrastructure access.
- No assumption that a cross-domain browser login implies shared tenant access.

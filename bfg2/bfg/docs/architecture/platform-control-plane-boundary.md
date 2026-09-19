# ADR: Separate the superuser control plane from the workspace console

**Status:** Accepted  
**Date:** 2026-09-20  
**Deciders:** Platform maintainers

## Context

The existing `/api/v1/platform/console/` API is a tenant-facing console. It is
intentionally shared by workspace owners and platform operators for workspace
details, extensions, invoices, and usage. Current `main` also has billing,
entitlement, metering, and variable tables that the console consumes.

The Platform operations requested for workspace lifecycle, cluster inventory,
audit history, runtime policy, import/export, and password-reset delivery have
a different trust boundary. They must be callable only by a Django
`is_superuser` account. Replacing the owner console or creating duplicate
entitlement, meter, variable, or migration models would break current
Workspace management and make historical data ambiguous.

## Decision

Keep `/api/v1/platform/console/` as the workspace-owner/shared console. Add a
separate `/api/v1/platform/control/` control-plane API for the operations that
manage the deployment or another workspace. Every control-plane endpoint uses
`IsAuthenticated` plus a permission that checks only `request.user.is_superuser`.
It returns a Bearer challenge for anonymous requests and a safe 403 for every
authenticated non-superuser.

The control plane reuses the models and services already present on `main` for
pricing, usage, and entitlements. New persistence is additive only when it has
no equivalent: auditable action requests, cluster-health observations, and
lifecycle records. Each write requires an explicit confirmation, a reason, and
a stable idempotency key where a retry could repeat an effect.

The client keeps owner pages on `/console/`; only the Platform navigation and
operator actions call `/control/`. A Platform superuser is identified by the
server's explicit `is_platform_superuser` field, not by the historical
`is_platform_admin` staff fallback.

## Options considered

### Replace `/console/` with the new implementation

This would make route ownership simple, but removes owner-facing extension and
billing behavior and collides with existing data models and migration numbers.

### Keep both implementations under `/console/`

DRF router registration cannot safely distinguish duplicate list/detail routes
by permission. It would create order-dependent behavior and could expose a
control-plane list to a staff account.

### Separate `/control/` from `/console/`

This leaves the tenant contract stable, makes the trust boundary visible in the
URL and code, and permits a focused superuser-only test matrix. It is the
chosen option.

## Consequences

- Existing Workspace owner and extension-management paths remain compatible.
- Legacy Platform-admin routes must not remain as staff-accessible aliases for
  control-plane writes; callers migrate to `/control/`.
- New migrations depend on the current `main` migration leaves and reuse the
  existing entitlement/meter/variable tables where appropriate.
- UAT requires real superuser and ordinary-user smoke tests; a JWT fabricated
  for a test does not prove this boundary.

## Action items

1. Implement the `/control/` routes and strict permission class on top of
   current `main`.
2. Port lifecycle, cluster, audit, and idempotency behavior without creating
   duplicate Platform policy models.
3. Move Platform-only client calls to `/control/`; retain `/console/` for owner
   actions.
4. Verify database migration from current `main`, Python security tests,
   client build, and real UAT superuser/non-superuser behavior.

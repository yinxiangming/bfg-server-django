# Platform data-plane adapter contract

## Purpose

The Platform control plane may reserve capacity, suspend a Workspace, and keep
an audit trail. It must not claim that it archived, restored, or migrated
tenant data unless a deployment-specific data-plane adapter has completed and
verified those operations.

This document is the required contract before enabling either the scheduled
deletion purge worker or cross-Cluster live migration. It applies to every
Cluster implementation, including a shared database deployment.

## Trust boundary

- Only a Django `is_superuser` control request can create an operation.
- The control plane signs an opaque, short-lived operation envelope for one
  named Cluster adapter. The browser never receives adapter credentials or a
  generic remote URL.
- The adapter authenticates the envelope, binds it to the requested workspace,
  and deduplicates by the operation UUID.
- Adapter progress callbacks are authenticated server-to-server and carry no
  customer records or response bodies in Platform audit events.
- A delayed callback must include the profile fencing version issued by the
  reservation. The control plane rejects it after rollback, expiry, or a newer
  placement request.

## Archive and restore protocol

Before a deletion purge can be enabled, an adapter must produce a versioned
archive manifest with all of the following:

1. Workspace identity, schema/data format versions, creation timestamp, and
   immutable archive object references.
2. A complete tenant database snapshot, including rows reachable through
   extension-owned models, and checksums for each exported object.
3. A private-media inventory with object keys, versions or ETags, byte counts,
   checksums, and a record of each object copied to isolated archive storage.
4. A read-back verification result for the stored database and every media
   object. Missing or mismatched objects fail the operation.
5. An isolated restore test against a disposable workspace/database namespace,
   with verification of row counts, object checksums, and a tenant-scoped API
   smoke test. The restored namespace must be destroyed by the adapter, not by
   the Platform control request.

The manifest reference, checksum, verification result, and restore-test result
are persisted before any delete is considered. The purge worker remains off by
default, previews its candidates, locks the profile, rechecks that it is still
inactive and due, and records one final idempotent audit event after success.
It must not delete database rows or media merely because a relational cascade
would remove a reference.

## Live migration protocol

A live migration is a single fenced operation, not an export/import and not a
`WorkspacePlatformProfile.cluster` update. The adapter must report these
idempotent phases in order:

1. `source_fenced` — new writes are drained or rejected at the source.
2. `snapshot_copied` — database and media snapshot copied to target staging.
3. `snapshot_verified` — target checksums and workspace identity verified.
4. `cutover_ready` — target can serve the workspace without browser-visible
   credentials or cross-tenant routing.
5. `routing_cutover` — control plane changes the profile only after verifying
   the original fence, then emits an audit event.
6. `rollback_window_open` or `completed` — source retention and rollback
   expiry explicitly recorded.

Any phase may enter `failed` with a secured adapter error reference. The
browser sees a generic failure. Before routing cutover, rollback releases the
reserved target capacity and invalidates the fence. After cutover, rollback is
an adapter-owned compensating operation; it cannot simply set the old Cluster
identifier back.

## Required adapter operations

| Operation | Required inputs | Completion evidence |
| --- | --- | --- |
| `archive_workspace` | workspace ID, archive operation ID | versioned manifest and read-back result |
| `restore_verification` | manifest reference, isolated target namespace | isolated API and checksum verification |
| `purge_workspace` | verified manifest reference, explicit execution ID | final deletion evidence and audit reference |
| `migrate_workspace` | source/target IDs, reservation ID, fencing version | ordered phase events and verified cutover |
| `rollback_migration` | migration operation ID, current phase | compensating-operation evidence |

## Release gates

No deployment enables `retention_purge` or `live_cluster_migration` until the
adapter's integration tests prove: tenant isolation, idempotent retries,
source/target authentication, a failed-copy rollback, an expired-reservation
callback rejection, archive read-back, and isolated restore. UAT must then run
one non-production workspace through the complete workflow before production
enablement.

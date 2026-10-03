# BFG Cluster runbook

Use this runbook after selecting the logical-routing or physical-infrastructure
mode in `SKILL.md`.

## Cluster field matrix

| Field | Required decision | Notes |
| --- | --- | --- |
| `id` | Stable unique identifier | Maximum 32 characters. Prefer environment and region, such as `brand-uat-nz`. Do not rename after assignment. |
| `name` | Operator-facing name | Include the brand or infrastructure purpose and environment. |
| `region` | `us`, `eu`, or `apac` | Classification only unless project code adds placement logic. |
| `api_base_url` | Public BFG API origin | Use the shared API for a logical cluster or the new API for a physical cluster. |
| `frontend_base_url` | Workspace frontend root | `https://uat.example.com` produces `<workspace-slug>.uat.example.com`. |
| `db_host`, `db_port` | Infrastructure metadata | A Cluster row does not create or select a database connection automatically. Never embed a password. |
| `redis_url` | Infrastructure metadata | Do not commit or print credentials. Confirm how the target project uses this field. |
| `s3_bucket` | Infrastructure metadata | Record the bucket name, not an access key. |
| `max_workspaces` | Admission limit | Explicit Cluster assignment locks the Cluster and counts actual bound profiles; zero admits no new profiles. |
| `current_workspaces` | Legacy counter | Not maintained by core creation. Control API reports `workspace_count` from actual profile relationships. |
| `is_accepting_new` | Admission policy | Enforced by `WorkspaceService._available_cluster` when a Cluster is explicitly passed; direct profile writes bypass it. |
| `is_active` | Operator status | Do not assume it tears down or disables infrastructure. |
| `health_status` | Recorded probe status | Use the protected health-check action and stored observations; see health restrictions below. |

## Read-only preflight

Run against the exact environment being changed. Adapt app labels only when the
target project uses a different installed-app layout.

```python
from django.apps import apps

Cluster = apps.get_model("platform", "Cluster")
Profile = apps.get_model("platform", "WorkspacePlatformProfile")
Domain = apps.get_model("common", "WorkspaceDomain")

for cluster in Cluster.objects.order_by("id"):
    print({
        "id": cluster.id,
        "api_base_url": cluster.api_base_url,
        "frontend_base_url": cluster.frontend_base_url,
        "active": cluster.is_active,
        "accepting_new": cluster.is_accepting_new,
        "profile_count": Profile.objects.filter(cluster=cluster).count(),
    })

for profile in Profile.objects.select_related("workspace", "cluster"):
    if profile.cluster_id:
        domains = list(Domain.objects.filter(
            workspace=profile.workspace,
            kind=Domain.KIND_SYSTEM_DEFAULT,
        ).values_list("hostname", flat=True))
        print({
            "workspace": profile.workspace.slug,
            "cluster": profile.cluster_id,
            "system_domains": domains,
        })
```

Do not print API keys, Redis credentials, database credentials, authentication
tokens, or user data as part of the inventory.

## Logical brand-routing cluster

Use this mode when multiple brands share one backend but need different
Workspace domain suffixes.

### Infrastructure and routing

- Reuse the approved environment's `api_base_url`.
- Give the brand and environment their own `frontend_base_url`.
- Bind the wildcard domain to the project that serves Workspace UI, not merely
  to the marketing or Brand Portal BFF project.
- Verify wildcard DNS and a valid wildcard TLS certificate with an unused probe
  hostname before assigning Workspaces.
- Keep UAT and Production domain roots and Cluster records separate.

### Brand Portal binding

- Load and activate the Brand Portal extension on the intended Brand Workspace.
  This can be separate from the global Platform management Workspace.
- Assign the Brand Workspace's `WorkspacePlatformProfile.cluster` to the
  new Cluster.
- Configure registration, default country, currency, language, theme, plan, and
  provisioning extensions in the Brand Portal profile.
- Use the generic workspace create/provision ``skin`` field for an explicit core
  skin, or Brand Portal ``default_theme`` for brand-wide provisioning. An
  extension skin must be declared in the deployed server manifest and the same
  extension must appear in ``provisioning_extensions``. A blank explicit theme allows an activated extension to supply its default;
  inspect that extension rather than promising a particular theme.
- Create a dedicated Workspace-scoped API key for the brand BFF.
- Configure the BFF API origin, key, secret, and exact callback origin as
  server-only values.

The Cluster selects routing. It must not be used as a substitute for Brand
Portal extension defaults or BFF credentials.

## Physical infrastructure cluster

Before creating an active Cluster record, provision and verify:

- API runtime and immutable release version
- database, backups, migrations, restore test, and connection limits
- Redis, Celery broker/result backend, persistence policy, and isolation
- object storage, CORS where needed, lifecycle policy, and CDN
- secret management and credential rotation
- Workspace frontend deployment and wildcard host routing
- DNS, wildcard TLS, health checks, logs, metrics, alerts, and error reporting
- email and other environment-specific integrations
- network restrictions, firewall rules, and administrative access
- rollback path and disaster-recovery ownership

Only then create the Cluster record, initially with new assignment disabled.
Run smoke tests, mark it active and accepting new Workspaces, and perform a
single canary Workspace provisioning before broader use.

## Assignment behavior and migration safety

The following is an internal service pattern or authorized repair example, not
an unaudited production configuration shortcut. Snapshot affected domain rows
and check capacity; use a maintained assignment service when the host supplies one.

Ordinary assignment should save the profile so BFG's signal materializes the
system domain:

```python
profile.cluster = target_cluster
profile.region = target_cluster.region
profile.save(update_fields=["cluster", "region", "updated_at"])
```

Before changing an existing Cluster's `frontend_base_url`, produce an impact
list of every bound Workspace and its current system domain. Saving the Cluster
causes all of those system domains to be regenerated. Plan redirects and cache
invalidation before changing a live domain root.

Moving only a Brand Workspace changes the Cluster inherited
by future provisionings. Existing customer Workspaces retain their own profile
assignment until explicitly migrated.

## Validation checklist

### Data

- Cluster fields match the approved plan.
- Only intended profiles reference the Cluster.
- Every test Workspace has exactly one `system_default` domain.
- The hostname equals `<workspace-slug>.<frontend-root-host>`.
- Brand Portal provisioning records point to the expected source and target
  Workspaces.
- Expected extensions are active and entitled on the target Workspace.

### Network and user path

- API health and authenticated Brand Portal configuration calls succeed.
- A random wildcard hostname resolves and completes TLS.
- Registration and one-time email verification succeed with a disposable UAT
  account.
- Provisioning creates a new Workspace on the intended Cluster.
- The expected extension loads.
- The one-time SSO code opens the new Workspace and cannot be replayed.
- Cross-brand and cross-Workspace access remain denied.

### Release evidence

- Capture non-secret database output, DNS/TLS results, deployment revision,
  test results, and rollback target.
- Deallocate cost-managed UAT infrastructure after testing when required by the
  project runbook.
- Do not promote to Production solely because unit tests or an API smoke test
  passed.

## Rollback

For a logical routing change:

1. Stop new registrations or assignments if the user path is unsafe.
2. Rebind only affected profiles to the previously recorded Cluster.
3. Reconcile their system-domain rows through the normal save/service path.
4. Invalidate old and new hostname caches.
5. Restore the previous frontend route or redirect policy.
6. Re-run tenant-isolation and SSO checks.

Do not delete the new Cluster, DNS record, or certificate until no Workspace,
provisioning attempt, or rollback plan depends on it.

## Control-plane API contract

Inspect `bfg2/bfg/platform/urls.py`, `permissions.py`,
`views/control_views.py` and `services/control_actions.py` in the pinned revision.

| Operation | Endpoint | Required inputs |
| --- | --- | --- |
| Capability check | `GET /api/v1/platform/control/status/` | Authenticated Django superuser |
| Inventory | `GET /api/v1/platform/control/clusters/` | Same; response is an array |
| Create | `POST /api/v1/platform/control/clusters/` | Cluster fields, `confirm: true`, reason >= 3 characters, `X-Idempotency-Key` (8-128 characters) |
| Update | `PATCH /api/v1/platform/control/clusters/<id>/` | Same guard fields and `expected_version` from `config_version` |
| Health summary/history | `GET .../clusters/health-summary/`, `GET .../clusters/<id>/health-observations/` | Protected reads; no remote probe |
| Probe | `POST .../clusters/<id>/health-check/` | Confirmation, reason and control idempotency header; outbound request and stored audit/observation |

The control permission is Django `is_superuser`, not merely `is_staff`, a
Workspace admin role, or a historical embedded management membership. Inspect
host middleware for any required Workspace header; it is context, not a grant.
Cluster create requires non-empty `id`, `name`, `region`, `api_base_url`,
`db_host`, `redis_url` and `s3_bucket` in the current API. A tenant registration
also needs a usable `frontend_base_url`, even though Cluster create permits it
blank. Use real local resource settings when a field is required; do not invent
production resources or imply a required metadata field provisions them.

Updates also refuse a capacity below the existing profile count, and an inactive
Cluster cannot accept new tenants. Successful configuration changes increment `config_version`.
Updates use optimistic configuration versions. On a conflict, re-read and review
the change. Completed identical requests replay with the same idempotency key.
An incomplete request returns `409 idempotency_request_incomplete`: inspect the
audit log and actual state first, then retry with a new key as the API requires.
Do not retry uncertain side effects blindly. Preserve the audit trail by
using this API instead of ordinary direct ORM writes for Cluster mutations.

## Health probes and local development

`services/cluster_health.py` permits only operator-allowlisted HTTPS hostnames
at port 443 and the fixed `/api/v1/health/` path. Configure
`CLUSTER_HEALTH_ALLOWED_HOSTS` for the actual deployment. IP literals, loopback
HTTP URLs, credentials, redirects, query strings and custom ports are refused.
Do not weaken these restrictions to make a localhost probe turn green.
A stored or summary health read is not a new outbound probe; freshness is based
on observations from the last 24 hours.

Domain derivation discards the port and stores a hostname. The public frontend
resolver returns HTTPS. Therefore `http://localhost:3012` does not produce a
usable tenant URL by itself. For end-to-end local registration use a controlled
tenant domain, local host routing and trusted TLS, or report that domain/SSO
validation remains incomplete. Keep self-signed-warning handling with the user.

## Current implementation boundaries

Re-check these statements against the pinned revision:

- Passing a Cluster into `WorkspaceService.create_workspace` locks the row and
  rejects inactive, closed or full targets. Admission uses actual profile counts,
  not `Cluster.has_capacity`'s legacy counter. Direct assignment is not a capacity
  reservation; review capacity before changing existing profiles.
- Brand Portal provisioning inherits its Brand Workspace's Cluster. It does not
  select a fallback Cluster by region or create a Cluster on demand.
- Generic `/auth/register/`, `/auth/finalize-onboarding/` and Platform workspace
  creation are distinct paths. A region/default trial-domain setting is not
  Cluster assignment. Inspect those callers before promising parity.
- Current Brand Portal creation uses the same database. Standalone provisioning
  records local profiles/keys/operations; metadata is not a remote infrastructure
  or database provisioner. The placement queue is not a completed cutover engine.
- `current_workspaces` is a legacy counter. Control API inventory calculates
  actual bound profiles. Probe observations implement health tracking, but do not
  prove registration, tenant isolation or application readiness.
- MySQL does not create conditional unique constraints such as the one-active
  placement-reservation constraint. Review row-lock/fence service protections;
  a successful migration alone does not establish database-level enforcement.
- Domain regeneration may replace old system-domain rows. Back up mappings and
  honor the task's authorization for removals before bulk changes.

## Focused verification sources

Core tests live in `bfg2/tests/services/platform/test_platform_control_views.py`,
`test_platform_control_audit.py`, `test_workspace_creation.py`, and
`bfg2/tests/services/common/test_platform_workspace_provisioning.py`.
The hosting extension may supply `tests/test_provisioning.py` for Brand Portal
inheritance, missing-domain rollback, extension defaults and idempotent retries.
Run them with their declared test settings and an isolated test database. Never
point a test runner at the operator's imported production copy.

A successful probe establishes only the expected liveness response. The host
health endpoint may be static. Independently verify the intended database
host/database identity, migration state, authorized read/write canary and backup
restore before accepting an independent deployment. Never infer database health
or physical isolation from a green Cluster probe.

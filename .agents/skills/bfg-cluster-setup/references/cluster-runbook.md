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
| `max_workspaces` | Capacity policy | Operational metadata in the current core implementation. |
| `current_workspaces` | Observed usage | Read-only in Django admin; reconcile it before relying on capacity reporting. |
| `is_accepting_new` | Admission intent | Do not assume it blocks every custom provisioning path. |
| `is_active` | Operator status | Do not assume it tears down or disables infrastructure. |
| `health_status` | Operator status | Requires an external or project-specific health updater. |

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

- Activate the private Brand Portal extension on the management Workspace.
- Assign the management Workspace's `WorkspacePlatformProfile.cluster` to the
  new Cluster.
- Configure registration, default country, currency, language, theme, plan, and
  provisioning extensions in the Brand Portal profile.
- Use the generic workspace create/provision ``skin`` field for an explicit core
  skin, or Brand Portal ``default_theme`` for brand-wide provisioning. An
  extension skin must be declared in the deployed server manifest and the same
  extension must appear in ``provisioning_extensions``. A blank value safely
  falls back to the core ``store`` skin.
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

Moving only a Brand Portal management Workspace changes the Cluster inherited
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

## Current core limitations

Verify these against the pinned BFG revision before relying on them:

- `Cluster.has_capacity` is a model property; core Workspace creation and
  custom Brand Portal provisioning may not enforce it.
- `current_workspaces` is not automatically maintained by the core paths.
- health fields require an external or project-specific updater.
- infrastructure metadata does not provision or dynamically select database,
  Redis, storage, or frontend resources.

Treat admission control, health, and capacity as operator gates unless the
target project adds explicit enforcement.

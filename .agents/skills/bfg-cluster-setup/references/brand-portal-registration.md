# Brand Portal registration and Cluster inheritance

The flow below uses the bundled reusable Branding extension at
`extensions/branding/server`. Marketing websites and BFF deployments are
separate host-owned components. Recheck their installed revisions and contracts
before applying the plan.

## Components and ownership

| Component | Responsibility | Configuration owner |
| --- | --- | --- |
| Marketing/branding website | Public content and registration/login UI | Brand frontend |
| Same-origin BFF | Validated fixed API routes, server-only credentials, protected onboarding/session cookies | Brand frontend server |
| Brand Workspace | Portal configuration, registration switch and default tenant extensions/theme/locale | Brand Portal extension |
| Cluster | Tenant API and domain root, resource metadata, admission and recorded health | Platform superuser |
| Tenant Workspace | Store/business data, staff permissions, durable owner membership, domains and enabled extensions | BFG and installed extensions |

The branding website need not be the deployment serving wildcard tenant hosts.
A marketing Workspace ID or API URL alone is not a Cluster association. Resolve
`Brand Workspace -> WorkspacePlatformProfile.cluster -> Cluster` in the target
database. Find the Brand Workspace using its scoped API key/configuration, not
its display name alone. Do not print key secrets or create it from a guessed name.

## Locate the extension and host prerequisites

Brand Portal is a hosting-project extension, not guaranteed core Server code.
Locate its manifest, models, services, views, migrations and provisioning tests
through `apps/brand_portal` or the host's extension repositories. Confirm both
that Django loads the app and that the intended Workspace activates it; tables
existing in an imported database do not establish either condition.

Inspect `BrandPortalProfile`, `_portal_cluster`, `_execute_attempt`,
`_provision_baseline`, and the portal register/verify/finalize/SSO views.
Current defaults are `registration_enabled`, `provisioning_extensions`,
`default_theme`, `default_plan`, `default_country`, `default_currency`, and
`default_language`. The inspected provisioning path records `default_plan` in
its operation details; it does not itself grant a billing entitlement. Verify
the billing/entitlement service before promising an active subscription. Validate them through the extension's maintained management
API/service. Extension-owned themes require the corresponding deployed extension
and a provisioning list permitting that extension. Do not copy one brand's theme,
plan or integrations into the generic Server skill.

## Configuration plan

1. Select logical shared-backend routing or independently deployed infrastructure.
2. Verify API, tenant frontend, wildcard host routing, TLS, email delivery and the
   requested environment. Keep local/UAT/production origins and keys separate.
3. Create/configure the intended Cluster via the guarded Platform control API.
4. Bind the Brand Workspace's platform profile to that Cluster through a normal
   save/service so domain signals run. Leave existing customer assignments alone.
5. Activate/configure Brand Portal on that Workspace and keep registration off
   until its dependencies and domain root are verified.
6. Set permitted extension defaults, theme, locale and plan through the extension.
7. Create a dedicated least-privilege Workspace-scoped API key for the BFF using
   the current extension permission contract.
8. Configure server-only `BFG_BRAND_PORTAL_API_URL`, `BFG_BRAND_PORTAL_API_KEY`,
   `BFG_BRAND_PORTAL_API_SECRET`, and exact
   `BFG_BRAND_PORTAL_CALLBACK_ORIGIN` in the branding deployment. Check the
   frontend's actual contract if it uses different names. None belong in
   `NEXT_PUBLIC_*`, URL parameters or logs. Callback origins must be pure
   origins without credentials, paths, queries or fragments. HTTPS is required
   except for permitted local loopback/localhost development origins; that
   local exception does not apply to Cluster health probes.
9. Permit the exact brand callback origin in the backend. Configure CORS for
   tenant wildcard origins on the actual API, while the branding browser talks
   only to its same-origin BFF. Verify required host-forwarding headers.
10. Enable registration within the authorized environment and run the canary flow.

The BFF API URL chooses the API endpoint it calls. The Brand Workspace Cluster's
frontend root chooses tenant system domains. These are separate controls.

## Registration and login flow

1. The website sends account registration to its BFF, which calls the fixed
   `/api/v1/brand_portal/v1/auth/register/` path with its scoped API key and trusted
   callback origin. The portal binds the account to that brand and sends email
   verification; this operation writes data and sends mail.
2. Verification supplies a short-lived onboarding proof. The BFF holds that proof
   in a host-only HttpOnly cookie, not browser-accessible storage or logs.
3. Workspace setup sends the verified proof and the portal `Idempotency-Key`
   through the BFF to `/auth/finalize/`. This header differs from the Platform
   control API's `X-Idempotency-Key`; follow each contract exactly.
4. Provisioning locks the account/attempt, checks the ownership limit, creates
   the tenant with the Brand Workspace's Cluster and establishes owner/admin
   access. It applies locale/store/notification defaults and approved extensions;
   an explicit portal theme wins over an extension's default theme.
5. It resolves the tenant frontend domain and returns a one-time SSO redirect
   through the BFF. Current portal redirects use `/auth/sso?code=...`, followed by
   the existing SSO exchange; do not replace this with JWT query parameters or a
   legacy direct-token callback. The code must not be logged or replayable.
6. Existing-user login returns allowed tenant choices. Start SSO only for a
   selected permitted tenant; test cross-brand/cross-tenant rejection as well.
   In host revisions supporting setup recovery, a password-authenticated,
   email-verified account with no completed provisioning can receive new setup
   proof when registration remains enabled. The BFF stores it in an HttpOnly
   cookie and returns only a setup flag. Do not interpret revoked access to a
   previously completed tenant as permission to re-enter this recovery flow.

The current `_portal_cluster` reads one preconfigured profile relationship. There
is no automatic geographic scheduler/fallback. A missing Cluster/root can fail
with `workspace_domain_unavailable`; tests require tenant creation to roll back.
The inspected service performs embedded/same-database provisioning. Do not claim
it has created tenant resources remotely merely because a profile has a Cluster
or remote UUID.

## Diagnose before changing configuration

| Observation | Next evidence |
| --- | --- |
| Cluster inventory is empty | Query the target database and environment; do not synthesize rows to conceal missing setup. |
| Website renders a registration form | Read the BFF config endpoint and extension state; UI presence does not prove provisioning works. |
| Generic website health is 200 | Inspect whether it probes upstream or merely reports env presence. |
| `portal_unavailable` (503) | Check scoped BFF variables and outbound API reachability without exposing values; the code can represent missing config or a connection failure. |
| Portal tables exist but routes are absent | Check `LOCAL_APPS`, extension linking/loading, migrations and Workspace activation independently. |
| Domain failure during finalize | Check Brand Workspace cluster, tenant frontend root and domain materialization. |
| Browser `Failed to fetch` | Check actual API origin, tenant host resolution and CORS preflight; an API health 200 is insufficient. |
| Repeated finalize or control request | Reuse the correct contract's idempotency key and inspect the stored attempt/action before retrying. |

Use a disposable account only in an authorized test environment. Verify one
complete register/email/finalize/extension/SSO flow, correct Cluster/domain,
rollback on missing domain, and code replay rejection. Record unsatisfied DNS,
TLS, email, activation or remote deployment prerequisites as unverified rather
than reporting setup complete.


## Local HTTP development

Bundled Branding is at `extensions/branding/server`, with its administrative
client plugin at `extensions/branding/client/plugins/brand_portal`. A deploying
host supplies marketing websites, origins, ports, and default business plugins.
Keep those deployment values outside BFG source code.

Local HTTP requires explicit development opt-ins. The domain resolver preserves
scheme and port only with `DEBUG` and `BFG_LOCAL_HTTP_FRONTEND`. Branding callback
origins must be validated loopback or localhost origins. A frontend BFF must
also opt in to local HTTP cookies using its own maintained configuration.
Production HTTPS and Secure cookies remain the default. Verify callback
validation, cookies, email links, CORS, and API routing independently.

# Server Feature Switches and Environment Toggles

This document summarizes the main server-side switches, feature flags, and operational environment variables used by the BFG server.

It focuses on runtime behavior toggles rather than secrets. Secret values such as API keys, DB passwords, and OAuth secrets are intentionally not documented here beyond their purpose.

## 1. Core Runtime

### `ENV`
- Default: `dev`
- Purpose: Chooses which environment file loading behavior to use.
- Notes:
  - `local` / `dev` loads `src/server/.env`

### `DEBUG`
- Default: `True`
- Purpose: Enables Django debug behavior.
- Impact:
  - Affects error pages, static/media handling, and logging verbosity.

### `SECRET_KEY`
- Default: `dev-secret-change-in-production`
- Purpose: Django signing key.
- Recommendation: Always override in production.

### `ALLOWED_HOSTS`
- Current behavior: effectively open (`['*']`)
- Purpose: Django host header allowlist.
- Recommendation: Lock this down in production.

---

## 2. Instance Mode / Deployment Topology

### `BFG_INSTANCE_TYPE`
- Default: `workspace`
- Allowed values:
  - `workspace`
  - `platform`
- Purpose:
  - Controls whether the server behaves like a standalone workspace node or a platform node.

### `WORKSPACE_API_URL`
- Default: `http://localhost:8000`
- Purpose:
  - For platform mode / dual-write flows, points to the workspace API.

### `PLATFORM_API_URL`
- Default: empty
- Purpose:
  - Optional platform API base URL.

### `PLATFORM_API_KEY`
- Default: empty
- Purpose:
  - Shared secret used by internal platform/workspace provisioning endpoints.

### `PLATFORM_WORKSPACE_SLUG`
- Default: empty
- Purpose:
  - Enables embedded platform mode when combined with `BFG_INSTANCE_TYPE=workspace`.

### `BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS`
- Default: `true`
- Purpose:
  - If enabled, Django superusers bypass tenant-level workspace permission checks.
- Recommendation:
  - Set to `false` for stricter multi-tenant production behavior.

---

## 3. Frontend / URL Routing

### `FRONTEND_URL`
- Default: empty
- Purpose:
  - Base frontend origin used for auth redirects, email links, and browser-facing callbacks.

### `WORKSPACE_FRONTEND_URL`
- Default: empty
- Purpose:
  - Fallback frontend URL for workspace-specific flows when profile/domain data is missing.

### `SITE_NAME`
- Default: `BFG`
- Purpose:
  - Human-readable site / instance name used in emails and metadata.

### `FRONTEND_EMAIL_CONFIRM_PATH`
- Default: `/auth/verify-email`
- Purpose:
  - Frontend route used in email confirmation links.
- Why it matters:
  - Lets projects route verification into a reusable onboarding flow such as `/onboarding/confirm-email` instead of hardcoding auth pages.

---

## 4. Onboarding / Registration Flow

### `EMAIL_VERIFICATION_REQUIRED`
- Default: `true`
- Purpose:
  - Controls whether email verification is required as part of signup / onboarding.
- Behavior:
  - `true`: verification emails are sent and frontend should block setup until verified.
  - `false`: signup can proceed directly into setup without mandatory email verification.

### `ONBOARDING_PROVISION_ON_REGISTER`
- Default: `true`
- Purpose:
  - Controls whether workspace/store provisioning happens immediately during registration.
- Behavior:
  - `true`: registration may provision workspace/store right away.
  - `false`: registration only creates the user; provisioning can be deferred until after verification or later onboarding steps.
- Why it matters:
  - This is the key switch for reusable multi-step onboarding flows.

### `BFG_MAX_OWNED_WORKSPACES_PER_USER`
- Default: `3`
- Purpose:
  - Caps how many workspaces one account can own when it creates them through `POST /api/v1/platform/workspaces/`.
- Behavior:
  - Counts the account's active owner memberships, suspended and inactive workspaces included.
  - Only an account that already owns a workspace, or is an active admin of one, can create a workspace at all; any other account gets `403` with `code: workspace_create_forbidden`.
  - Past the cap the endpoint answers `400` with `code: workspace_limit_reached` and the cap as `limit`.
  - `GET /api/v1/platform/workspaces/me/` reports the cap as `workspace_limit`, and as `create_blocked` the code a create request would get right now (`null` when it would succeed).

---

## 5. Authentication / Social Auth

Social-login credentials are **not** environment variables. They live in
`bfg.common.models.SocialAuthConfig`, and
`config.social_adapter.WorkspaceSocialAccountAdapter` reads them per request, so
the redirect flow, the OAuth callback and Google One Tap all resolve the same
client for the calling shop.

There are two levels:

- **Platform default** — a row with no workspace, managed by the operator in
  Django admin. Inherited by every workspace. This is enough for most shops: the
  redirect flow only ever returns to our own API domain, so one client
  registered for the platform carries all tenants.
- **Workspace client** — a row owned by a workspace, edited under **Admin →
  Settings → General → Social login**. It overrides the default. A shop needs
  one when it wants its own name on the provider's consent screen, or One Tap on
  its own domain: One Tap renders in the storefront's page and the provider
  checks that origin, with no wildcard support.

Precedence, per provider: a usable workspace row wins; a workspace row switched
to inactive means "off for this shop" and does *not* fall back; anything else
(no row, or a half-filled draft) inherits the platform default. A request that
cannot be traced to a workspace gets no social login at all.

The former `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, `FACEBOOK_APP_ID` /
`FACEBOOK_APP_SECRET` and `APPLE_CLIENT_ID` / `APPLE_SECRET` / `APPLE_KEY_ID` /
`APPLE_PRIVATE_KEY` variables are read exactly once more, by the migration that
turns them into the platform default row, and are ignored after that.

### Built-in behavior toggles (code-level)
These are set in Django settings rather than through env vars, but they are still important switches:

- `SOCIALACCOUNT_EMAIL_AUTHENTICATION = True`
- `SOCIALACCOUNT_AUTO_SIGNUP = True`
- `SOCIALACCOUNT_LOGIN_ON_GET = True`
- `ACCOUNT_ADAPTER = 'config.account_adapter.FrontendAwareAccountAdapter'`

The custom account adapter is important because it rewrites email confirmation links to use:
- `FRONTEND_URL`
- `FRONTEND_EMAIL_CONFIRM_PATH`

This makes verification/onboarding flows project-specific while keeping the core email verification backend reusable.

---

## 6. Email Delivery

### `EMAIL_BACKEND`
- Default: `django.core.mail.backends.smtp.EmailBackend`
- Purpose:
  - Chooses the email sending backend.

### `EMAIL_HOST`
- Default: `localhost`

### `EMAIL_PORT`
- Default: `1025`

### `EMAIL_USE_TLS`
- Default: `False`

### `EMAIL_USE_SSL`
- Default: `False`

### `EMAIL_HOST_USER`
- Default: empty

### `EMAIL_HOST_PASSWORD`
- Default: empty

### `DEFAULT_FROM_EMAIL`
- Default: `noreply@example.com`

These values together determine whether password reset and email confirmation mails can actually be delivered.

---

## 7. CORS / Browser Access

### `CORS_ALLOW_ALL_ORIGINS`
- Current default in code: `True`
- Purpose:
  - Allows browser requests from any origin.
- Recommendation:
  - Restrict in production.

### `CORS_ALLOW_CREDENTIALS`
- Current default in code: `True`

### `CORS_ALLOW_PRIVATE_NETWORK`
- Current default in code: `True`
- Purpose:
  - Helps local/private network browser access in development.

---

## 8. Media / Static Files

### `MEDIA_PUBLIC_BASE_URL`
- Default: empty
- Purpose:
  - Absolute base URL for media when storage returns relative paths.

---

## 9. Celery / Async Jobs

### `CELERY_BROKER_URL`
- Default: `redis://localhost:6379/0`

### `CELERY_RESULT_BACKEND`
- Default: `redis://localhost:6379/0`

These control background task processing for async jobs.

---

## 10. Practical Recommended Profiles

### A. Standard production onboarding (recommended)
```env
EMAIL_VERIFICATION_REQUIRED=true
ONBOARDING_PROVISION_ON_REGISTER=false
FRONTEND_EMAIL_CONFIRM_PATH=/onboarding/confirm-email
```

Use when you want:
- user registers first
- verifies email
- completes setup wizard
- only then provisions the store/workspace

### B. Fast internal/demo mode
```env
EMAIL_VERIFICATION_REQUIRED=false
ONBOARDING_PROVISION_ON_REGISTER=false
FRONTEND_EMAIL_CONFIRM_PATH=/onboarding/confirm-email
```

Use when you want:
- the same reusable onboarding UI
- but without blocking on email verification

### C. Legacy immediate-provision mode
```env
EMAIL_VERIFICATION_REQUIRED=true
ONBOARDING_PROVISION_ON_REGISTER=true
FRONTEND_EMAIL_CONFIRM_PATH=/auth/verify-email
```

Use when you want to preserve the older behavior where registration may provision the workspace immediately.

---

## 11. Metered Usage and Entitlements

Only relevant to a deployment that charges workspaces for what they use. A deployment that does not is unaffected by everything in this section and should leave it alone.

### `BFG_EXTENSION_ENTITLEMENT_CHECK`
- Default: empty
- Purpose:
  - Names a callable `(workspace, manifest) -> bool` deciding whether a workspace may use an extension at all, separately from whether it has switched it on.
- Behavior:
  - Empty (the default): every workspace is entitled to every deployed extension.
  - `bfg.platform.services.entitlements.entitlement_check` answers from the `platform.WorkspaceEntitlement` table — extensions priced as part of the base plan are always entitled, add-ons need a live entitlement row: `active` while its period runs and for `grace_days` after it ends (indefinitely when it has no period end), or `grace` until `grace_until` passes.
  - An entitlement lapses on time rather than on being swept, so nothing keeps working merely because a scheduled job has not run.
  - A check that raises makes that extension unavailable and is logged; it never fails the request that asked.
- Why it matters:
  - **Setting this without entitlement rows switches every add-on off at once.** Point it at the table only once the rows a deployment's workspaces should hold have been written, which is why it defaults to empty and is only ever read from the environment.
  - `python manage.py grant_entitlements --all-workspaces --switched-on --months 3 [--dry-run]` writes those rows: the base plan for every active workspace, plus every add-on each one currently has switched on, granted rather than sold. Run it before setting this, and a deployment that has been running without billing keeps everything it was using. It is safe to run twice — a workspace already entitled to a key is left alone — and `--dry-run` reports what it would grant without writing.
- What the console is told:
  - Every extension in the console's payload carries both `entitled` — the answer this check gives, whether the workspace may use it at all — and `available`, whether it is live right now, which also wants the extension switched on and everything it requires available. An add-on nobody has obtained is `entitled: false`; one obtained and then switched off is `entitled: true, available: false`. Without the switch set, `entitled` is true for everything.

### What an add-on costs, and acquiring one

- **A plan is a thing the deployment sells.** One `shop.SubscriptionPlan` on the platform workspace (`PLATFORM_WORKSPACE_SLUG`) per item, its `code` naming what it prices: the key of the add-on extension, or the empty string for the base plan itself — the same code `platform.WorkspaceEntitlement.KEY_BASE_PLAN` uses. Its `price` is one month, in the platform workspace's own currency. Leave no other plan of that workspace uncoded, since an uncoded one there reads as the base plan; a workspace's own plans, sold to its own customers, are unaffected and stay uncoded.
- **An add-on no plan names has not been priced**, and cannot be acquired until somebody prices it. That is a refusal (`no_plan`) rather than a free add-on, because the alternative is giving away whatever the deployment forgot to price.
- `POST /api/v1/platform/console/workspaces/<id>/extensions/<key>/acquire/` obtains one, for whoever may switch that workspace's extensions on. Priced at nothing, the entitlement is written and the extension switched on in one transaction, and the answer says `entitled: true`. Priced at anything else, an invoice is issued and **nothing else is written until it is paid**; the answer carries the bill. Asking twice for a priced add-on hands back the unpaid bill that already exists rather than issuing a second.
- Refused with 400 and a `code`: `already_entitled`, `not_an_addon` (it is part of the base plan), `no_plan`, and — for a bill that cannot be written — `no_owner`, `unknown_currency`, `no_exchange_rate`, `key_too_long`. 404 `unknown_extension` for a key no app declares.
- **Paying the bill is what writes the first period**, a month from the day the bill was issued, exactly as paying a monthly bill writes the next one; see below.

### `BFG_EXTENSION_PLAN_PACKS`
- Default: empty
- Purpose:
  - The set of extensions a kind of shop starts with, so the same question does not have to be answered for every new workspace.
- Shape:
  - A mapping of pack key to `{name, name_zh, description, description_zh, industries, extensions}`, or the dotted path of one (or of a callable returning one). `industries` names the setup wizard's industry keys the pack suits; `extensions` names extension keys.
  - `BFG_EXTENSION_PLAN_PACKS_FILE` takes the path of a JSON file of the same shape, for a deployment whose packs are data written by whoever runs it rather than code. Read once; a file that is missing or unparsable leaves the deployment with no packs and is logged. The setting above wins where both are given.
- Behavior:
  - The setup wizard applies the pack matching the industry a new shop picks, after the template has been written and outside its transaction — an extension's activation hook failing costs the shop its pack, not its currency, tax and pages.
  - `python manage.py plan_packs list` shows what is configured; `python manage.py plan_packs apply <pack> --workspace <id|slug> [--dry-run]` applies one to a workspace that already exists.
  - **Applying only ever switches things on.** It never deactivates anything, including extensions the pack does not mention, and it never grants an entitlement: a key the workspace is not entitled to is reported and skipped, so a pack can be offered to somebody who has not bought everything in it.
  - A key the workspace is not entitled to is reported and skipped unless `BFG_EXTENSION_PACK_OBTAIN` names a way to obtain it (below).
  - A pack naming an extension the deployment does not ship drops that key and logs it once, next to the pack that named it.
  - Two packs claiming one industry is a configuration mistake; the first wins, so the answer at least stays the same between calls.

### `BFG_EXTENSION_PACK_OBTAIN`
- Default: empty
- Purpose:
  - Names a callable `(workspace, manifest) -> bool` asked whether a workspace may now have an add-on a plan pack named and the workspace is not entitled to. Returning true means the pack asks again.
- Behavior:
  - Empty (the default): nothing is obtained and every unentitled key a pack names is skipped with its reason.
  - `bfg.platform.services.acquisitions.pack_obtain` obtains an add-on **priced at nothing** and refuses one with a price: a pack is not a purchase, and nothing may commit a workspace to a bill it has not been shown. A priced add-on stays skipped, which is what puts it in front of somebody as a thing to buy.
  - Asked once per refused key, and only for keys a pack named. A hook that raises skips that key and is logged; the rest of the pack still applies.

### Platform variables
- Margins, grace periods, retention windows and the default usage cap are rows in `platform.PlatformVariable`, not environment variables: they are policy an operator adjusts while the deployment runs, and each change is recorded in `platform.PlatformVariableChange` with who made it and why.
- Read and write them through `bfg.platform.services.platform_variables` (`get_variable`, `set_variable`, `all_variables`). Every variable the deployment recognises is declared there with its default, so a deployment that has never set one still behaves sensibly, and an unrecognised key is refused rather than stored.
- A running deployment changes them from the console rather than from a shell; see [The console, for whoever runs the deployment](#the-console-for-whoever-runs-the-deployment) below.

### Metered calls
- A meter is a named unit worth counting, declared by the extension that spends it (`meters` on its manifest). Its price is a `platform.MeterPrice` row: a vendor cost, how many calls or tokens that cost buys, an optional margin, and the moment it takes effect. A new rate is a new row, so bills already calculated stay explicable.
- One point is one US dollar. Usage is totalled per workspace, meter and UTC day in `platform.UsageRecord`.
- A workspace may run up `WorkspacePlatformProfile.monthly_usage_cap_points` in a calendar month, or the `monthly_usage_cap_points` variable when it has no cap of its own.
- Callers ask `bfg.platform.metering.allowed(workspace, meter)` before spending and `bfg.platform.metering.meter(workspace, meter, quantity)` after the call succeeded.
- Prices are read and written with `python manage.py meter_prices list` and `python manage.py meter_prices set KEY --cost 0.15 --unit-size 1000000 [--margin 0.30] [--from 2026-10-01T00:00:00Z]`, or from the console. `list` shows each meter's whole history with the row in force marked; `set` only ever adds a row, and neither the command nor the console can edit or delete one.
- The assistant (`POST /api/v1/agent/chat/`) meters its own model calls as `ai.<model>.input`, `ai.<model>.input_cached` and `ai.<model>.output`, `<model>` being the lowercased id of the model actually asked — the model that answers and the cheaper one that picks its tools fill separate meters. Price every meter a deployment's `OPENAI_MODEL` and `OPENAI_TOOL_SELECTOR_MODEL` will fill; an unpriced meter is logged and goes uncounted rather than billed as free.
- A workspace over its cap gets `402` with `{"code": "usage_cap_reached"}` from that endpoint, asked once per request before anything is sent.
- A meter nothing has priced yet is logged as a warning once an hour per meter, not as an error with a stack trace on every call: wiring a meter up before pricing it is what every rollout looks like for a while. Nothing is billed for it until a `MeterPrice` row exists, so watch for that warning after switching a new meter on.

### The billing month

There is no scheduler in this library, and the deployments it was written for run no Celery beat. The three steps below are management commands, to be run from cron or by hand. All three are safe to run twice.

- `python manage.py close_entitlement_periods [--dry-run]` — moves an entitlement past its period into `grace` (for `grace_days`, counted from the period's own end), and one past its grace into `ended`. Ending one pauses the extension it paid for: `WorkspaceExtension` goes to `paused`, keeping the workspace's data and configuration, so paying again restores it. Run daily. Running it late delays the pause, not the expiry — an entitlement stops counting on time either way.
- `python manage.py refresh_exchange_rates [--base USD] [--symbols NZD,CNY]` — stores the ECB's daily reference rates (through Frankfurter; free, no key) in `finance.ExchangeRate`, under the day the bank published them. Run daily, and in any case before issuing bills. Every published rate is read and the ones the deployment has currencies for are kept, so a currency the bank does not publish is logged and skipped rather than costing the refresh every other currency. A refresh that fails writes nothing and leaves the rates already on file, which is what conversions then use. A day the feed could not be read for at all leaves that currency unbillable until somebody enters the rate by hand from the console, which records that it was typed rather than published; a later refresh that does reach the feed replaces it with the published number.
- `python manage.py issue_monthly_bills [--month YYYY-MM] [--dry-run]` — issues one invoice per workspace for a month of metered usage and the entitlements whose period ended in it, defaulting to last month. The invoice is issued by the platform workspace (`PLATFORM_WORKSPACE_SLUG`) and made out to the workspace's owner, in the workspace's own currency at the day's rate; it falls due after `invoice_due_days`. Its number is `PLAT-<workspace id>-<YYYYMM>`, which is what stops a month being billed twice — the unique index on (workspace, invoice number) refuses the second attempt — and is, with the platform workspace itself, how an invoice is tied back to the workspace it is about.

A platform invoice number has two shapes, and both start `PLAT-<workspace id>-` so that everything reading a workspace's bills by prefix — what it owes, what the console lists — reads all of them:

| Number | What it bills | What paying it writes |
|---|---|---|
| `PLAT-<workspace id>-<YYYYMM>` | a month of usage and the renewals that fell in it | the next period of everything the bill renewed |
| `PLAT-<workspace id>-ADD-<key>-<n>` | one acquisition of one add-on | that add-on's first period, a month from the issue date |

`<n>` counts the workspace's acquisitions of that add-on, so buying it again after it lapsed is a new number. Each shape is read back by its own function and neither reads the other's. The whole number has to fit `finance.Invoice.invoice_number` (50 characters), which is what bounds how long an add-on's key can be if the deployment means to sell it.

Three things about a bill are worth knowing before switching this on:

- **Bills are for the month that ran.** An entitlement is billed for the month its period ended in, whatever has become of it since — including one that lapsed and one a sweep has already moved to `ended`. Reading only the rows still live would make whether a month is billed depend on whether `close_entitlement_periods` ran first, which for a fortnight's grace would silently drop every period ending in the first half of a month. Issuing a bill does not itself write the next period; renewing is a purchase.
- **Tax is only worked out for New Zealand**, at whatever rate the platform workspace has recorded for `NZ` in `finance.TaxRate`, applied over the whole invoice. Every other country is billed untaxed, which is right for some and wrong for others; nothing yet records a customer's tax registration, so do not sell into a country whose rules have not been settled first.
- **The trial credit is a one-off.** The `trial_points` variable comes off a workspace's first bill, never more than the bill itself, and `WorkspacePlatformProfile.trial_points_used_at` records that it has been spent. A first bill smaller than the credit does not keep the difference.

**Paying a bill is what buys the period**, whichever shape it is, and it is heard three ways — a gateway payment, `InvoiceService.mark_as_paid`, and the status written straight onto the row by the invoice editor — all of which end up in the same idempotent place. A period is worked out from the invoice rather than from when the money arrived, so paying late buys the same period as paying on time, and the same payment reported twice writes it once.

### What an unpaid bill stops

A workspace with a platform invoice that is past its due date and unpaid may not make another metered call: `bfg.platform.services.usage.may_meter` refuses it, and so `metering.allowed` does too. Nothing else stops — the shop, its orders and its data all keep working, and only what costs the deployment money on the workspace's behalf is withheld. An invoice that came to nothing (a month covered entirely by the trial credit) is not a debt and stops nothing, and only the platform workspace's own invoices count, since a workspace chooses what its own invoices are numbered. The answer is cached for a minute, so a workspace that has just paid is unblocked within one. An unpaid *bill* and a lapsed *plan* are separate questions with separate answers: this one withholds metered calls, and the switch below is what stops a lapsed plan being written to at all.

### `BFG_READ_ONLY_WHEN_UNENTITLED`
- Default: `false`
- Purpose:
  - Puts a workspace whose base plan has lapsed past its grace period into **read only**: writes are refused with `403` and `{"code": "workspace_read_only"}`, apart from an explicit list below. Nothing is deleted, nothing is hidden, and paying restores it.
- **Do not switch this on until every workspace that should have a base plan has a `platform.WorkspaceEntitlement` row for it.** The check asks that table, and a workspace with no rows answers "no plan" — so switching this on first makes *every* workspace on the deployment read-only at the same moment. This is the same trap as `BFG_EXTENSION_ENTITLEMENT_CHECK`, and the reason this is a settings switch rather than a default.
- Wiring:
  - `bfg.platform.middleware.ReadOnlyWorkspaceMiddleware`, installed after `bfg.common.middleware.WorkspaceMiddleware`. Installing it does nothing on its own; with the switch off it costs one attribute lookup per request and asks the database nothing.
- Behavior:
  - **Reads are never refused.** GET, HEAD and OPTIONS always pass, so the shop can be browsed, the back office read, and every export used — all of the exports in this library are GETs.
  - **Endpoints outside any workspace are never refused**, which covers signing in, refreshing a token, registering, and the whole platform console (`/api/v1/platform/`).
  - **Still allowed, and marked as such on the views themselves** (`bfg.core.read_only.exempt_from_read_only`; the list with its reasoning is in `bfg.platform.middleware`):
    - `POST /api/v1/platform/workspaces/{id}/checkout/` — paying for the plan; the way out.
    - `POST /api/v1/platform/webhooks/stripe/` — the gateway confirming the payment.
    - `POST /api/v1/me/change-password/` and `/api/v1/me/reset-password/` — account, not workspace.
    - `POST /api/v1/store/payments/callback/{gateway}/` — money a shopper has already parted with.
    - `POST /api/v1/shop/orders/{id}/update_status/`, **for an order already marked paid only**.
    - `POST /api/v1/delivery/carriers/{id}/ship_order/`, and a consignment's `update_status`, `add_tracking_event` and `generate_label` — getting goods to shoppers who have already paid.
  - **Refused**, among everything else: customer registration, cart and checkout, creating or editing orders, `mark-paid`, refunds, cancellations, all catalogue/settings/marketing writes, storefront analytics collection, and the assistant endpoints. API-key writes are refused the same way — the key is resolved in the middleware, because the workspace middleware leaves an API-key request tenant-less for the view layer to bind.
  - **Failing to decide means writable.** If the question cannot be answered — database unreachable, anything at all — the workspace is treated as writable and the failure is logged at ERROR. Closing a trading shop because of the fault that also stops anyone diagnosing it is the worse outcome.
  - The answer is cached for a minute (`bfg.platform.services.read_only.CACHE_SECONDS`), like the overdue-invoice answer. Whatever settles a payment should call `read_only.forget(workspace)` so the shop is trading on the next request rather than in a minute's time; `entitlements.grant` already does.
- What the clients are told:
  - `GET /api/v1/me/` carries `workspace_read_only` (boolean), so the admin can explain itself before the first refusal rather than after.
  - `GET /api/v1/settings/storefront/` carries `read_only` (boolean), visible to anonymous visitors, so the storefront can say the shop is not taking orders on the product page and at checkout. It says only that; never why, and nothing about what is owed. It is added outside the cached config payload, so a shop that has just renewed is not told it is closed until that cache expires.
  - Both fields are additions; no existing field changed.

### The console, for whoever runs the deployment

Everything above is stored in the database rather than in the environment, so it can be changed while the deployment runs. The management commands are one way in; `/api/v1/platform/console/` is the other, and the only one a deployment without a shell has.

Most of the console is shared with **workspace owners**, who reach the workspaces they own: the workspace list, one workspace with its extensions, its metered usage and its platform bills. The endpoints below are **not**: they set what every workspace is billed by, or give one workspace something it has not paid for, so anyone who does not administer the platform is refused all of them with `403 platform_admin_required` — the same answer for a workspace they own, one they do not and one that does not exist, which is what keeps the refusal from saying which. A platform administrator naming a workspace that is not one gets `404 workspace_not_found`, as the rest of the console does.

| Method | Path | What it does |
|---|---|---|
| GET | `/console/variables/` | Every variable, its default, what it is worth now, and the last change with the reason given for it |
| PATCH | `/console/variables/{key}/` | `{"value": ..., "reason": "..."}` — a reason is required and is kept in `PlatformVariableChange`; an undeclared key is `404`, a value the variable cannot hold `400` |
| GET | `/console/meter-prices/` | Every meter's whole price history, newest first, with the row in force marked (`?meter=` narrows it) |
| POST | `/console/meter-prices/` | `{"meter", "vendor_cost", "unit_size", "margin"?, "effective_from"?}` — adds a row and changes none. There is no detail route at all, so no request can edit or delete a price |
| GET | `/console/exchange-rates/` | The rates most recently stored, newest day first (`?base=`, `?currency=`, `?limit=`); `source` is `feed` or `manual` |
| POST | `/console/exchange-rates/` | `{"from", "to", "rate", "effective_date"?}` — a rate entered by hand for a day the feed could not be read for, recorded as typed and by whom |
| GET/PATCH | `/console/workspaces/{id}/usage-cap/` | One workspace's monthly cap. `{"cap_points": null}` puts it back on the deployment's default, which is **not** the same as `{"cap_points": "0"}` — a cap of zero stops it metering anything |
| POST | `/console/workspaces/{id}/grants/` | `{"key", "months" \| "never_expires", "reason"}` — an entitlement given rather than sold. `key` is an add-on's extension key, or `""` for the base plan, and is required even when empty |

Two things about a grant are worth knowing:

- **A workspace that already holds a live entitlement to the key is refused** with `409 already_entitled`, carrying the entitlement it already has, rather than given a second row. Two live rows for one key are two things to renew and two to explain, and a second grant is almost always the same grant made twice. One that has ended can be granted again.
- **The extension is not switched on.** What a workspace is entitled to and what it has switched on are separate, and switching one on changes what that workspace's staff and customers see, runs its activation hooks and can be refused by its prerequisites — the workspace's decision, not a side effect of being given something. The one exception is an extension **the platform itself paused** when an entitlement ran out: pausing kept its data and configuration so that being entitled again would restore it, so a grant resumes it. `extension` in the answer says which happened, and carries the refusal when the resume was declined; the grant stands either way.

---

## 12. Notes for Reusable Project Design

For future projects, the most reusable onboarding architecture is:

1. Server owns the policy:
   - whether email verification is required
   - whether provisioning happens at registration time or later
   - which frontend path handles email confirmation

2. Frontend consumes server policy:
   - marketing pages / skins can vary by project
   - onboarding steps and routing stay reusable

3. Verification links should always point to a configurable frontend path rather than a hardcoded auth page.

This allows a new project to reuse the same backend/auth/onboarding capability with minimal changes:
- swap the visual shell
- swap copy/branding
- configure the frontend confirm path
- choose the verification/provisioning policy through env vars

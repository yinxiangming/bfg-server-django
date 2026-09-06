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

## 11. Notes for Reusable Project Design

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

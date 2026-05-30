# Feature: Email-First Onboarding Flow

## Overview
The legacy bfg-framework provisioned the workspace and staff records immediately upon registration. BFG also supports a lightweight, marketing-friendly **Email-First Onboarding Flow**.

## The Flow
1. **Marketing Page (`/get-started`)**: User inputs their email, store name, and password.
2. **Deferred Provisioning**: The server registers the `User` and sends a verification email, but **does not** create the `Workspace` or `Staff` records yet. The `User` is marked as inactive until the email is verified.
3. **Email Verification (`/auth/verify-email?key=...`)**: The user clicks the link in their email. The frontend calls the API to verify the email token.
4. **Onboarding Wizard (`/onboarding/get-started`)**: Once verified, the frontend pushes the user into a setup wizard to complete their store profile.
5. **Final Provisioning**: The user submits the final details, and the workspace is officially provisioned.

## Server Toggles
This flow is controlled by three main environment variables / settings located in `settings.py`:

- `EMAIL_VERIFICATION_REQUIRED` (default `True`): Forces allauth to send a verification email and block login until verified.
- `ONBOARDING_PROVISION_ON_REGISTER` (default `False`): 
  - If `True` (Legacy): `UserService.process_registration` creates the workspace immediately.
  - If `False`: Skips workspace creation during registration.
- `FRONTEND_EMAIL_CONFIRM_PATH` (default `/auth/verify-email`): The path appended to the frontend URL when allauth generates the email confirmation link.

## Implementation Details
- **Frontend State**: The registration details (email, store name) are temporarily held in `sessionStorage` (`pending_onboarding`) across the email verification boundary.
- **Verification Bridge**: When the user lands on `/auth/verify-email` from the email link, `AuthVerifyEmailClient.tsx` verifies the token via API. If successful, it updates `sessionStorage` (`emailConfirmed: true`) and routes the user seamlessly to `/onboarding/get-started` instead of forcing them back to a generic login page.
- **Tests**: E2E tests validate the server-side mechanics of this deferred provisioning flow.

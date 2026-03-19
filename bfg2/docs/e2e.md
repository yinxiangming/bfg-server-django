# E2E Tests

HTTP-only: run against any BFG2-compatible API. Set `BASE_URL` (or `BFG2_API_BASE_URL`) to the running server.

```bash
BASE_URL=http://localhost:3100 pytest bfg2/tests/e2e -m e2e -v
```

All passwords and secrets must come from **env** (e.g. `src/server/.env`). Do not hardcode them in tests.

## Env variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BASE_URL` | yes | API base URL |
| `BFG2_E2E_SUPERUSER_EMAIL` | optional | Pre-seeded bootstrap user (username or email) when `BASE_URL` ends with `:8000` and that deployment only allows a privileged user to create workspaces |
| `BFG2_E2E_SUPERUSER_PASSWORD` | with superuser email | Password for that bootstrap user |
| `BFG2_E2E_ADMIN_EMAIL` | when not using superuser bootstrap | Workspace admin email (default `admin@test.com`) |
| `BFG2_E2E_ADMIN_PASSWORD` | when not using superuser bootstrap | Password for workspace admin accounts |
| `BFG2_E2E_CUSTOMER_PASSWORD` | yes | Password for e2e customer accounts (`customer_e2e@test.com`, `customer2_e2e@test.com`, etc.) |
| `BFG2_E2E_TEMP_PASSWORD` | optional | Used only when `test_z_last_me_sensitive.py` change-password tests are enabled |

Sensitive me endpoints (`test_z_last_me_sensitive.py`) are skipped by default.

## Bootstrap behaviour

If `BASE_URL` ends with `:8000` **and** both `BFG2_E2E_SUPERUSER_EMAIL` and `BFG2_E2E_SUPERUSER_PASSWORD` are set, the session uses that account to create workspaces (one token for both workspaces when the API allows).

Otherwise the session registers/logs in `BFG2_E2E_ADMIN_EMAIL` with `BFG2_E2E_ADMIN_PASSWORD` and uses a second admin for the second workspace.

If token requests fail, confirm the server is up and env credentials match existing users.

## Restore e2e user passwords (reference API host DB)

When the API is backed by this repo’s Django app, you can align DB user passwords with `.env` from `src/server`:

```bash
cd src/server && python manage.py shell -c "
from pathlib import Path
import os
try:
    from dotenv import load_dotenv
    load_dotenv(Path('.env').resolve(), override=True)
except ImportError:
    pass
from django.contrib.auth import get_user_model
U = get_user_model()

def reset(identifier, password):
    if not identifier or not password:
        return 'skip'
    u = U.objects.filter(username=identifier).first()
    if not u and '@' in str(identifier):
        u = U.objects.filter(email__iexact=identifier).first()
    if not u:
        u = U.objects.filter(email=identifier).first()
    if not u:
        return 'missing ' + str(identifier)
    u.set_password(password)
    boot = os.environ.get('BFG2_E2E_SUPERUSER_EMAIL')
    if boot and identifier == boot:
        u.is_staff = True
        u.is_superuser = True
    u.save()
    return 'ok ' + str(identifier)

pairs = []
se, sp = os.environ.get('BFG2_E2E_SUPERUSER_EMAIL'), os.environ.get('BFG2_E2E_SUPERUSER_PASSWORD')
if se and sp:
    pairs.append((se, sp))
ae = os.environ.get('BFG2_E2E_ADMIN_EMAIL') or 'admin@test.com'
ap = os.environ.get('BFG2_E2E_ADMIN_PASSWORD')
if ap:
    pairs.append((ae, ap))
cp = os.environ.get('BFG2_E2E_CUSTOMER_PASSWORD')
if cp:
    for em in ('customer_e2e@test.com', 'customer2_e2e@test.com'):
        pairs.append((em, cp))
if ap:
    pairs.append(('admin2_e2e@test.com', ap))
for i, p in pairs:
    print(reset(i, p))
"
```

## Data prerequisites

- **finance/currencies**: At least one active currency must exist (seed via admin UI or migration). The `currency` fixture fails with a clear message if the list is empty.

## Checkout and coupons (expected failures)

Some cases are **normal business outcomes**, not bugs or flaky tests:

- **Coupon usage limit**: After a successful checkout that consumed the last allowed use, a second checkout with the same code should get **4xx** (e.g. 400) with a message about usage/limit. The server auto-reloads on code changes; ensure the process you hit with `BASE_URL` is that instance.

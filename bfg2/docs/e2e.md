# E2E Tests

HTTP-only: run against any BFG2-compatible API. Set **`BASE_URL`** to the running server.

```bash
BASE_URL=http://localhost:3100 pytest bfg2/tests/e2e -m e2e -v
```

All passwords and secrets must come from **env** (e.g. `src/server/.env`). Do not hardcode them in tests.

## What the suite covers

### Goals

- Exercise BFG2 over a **real HTTP API**: registration, web setup, catalog, orders, marketing, storefront, fulfillment, and related flows end-to-end.
- **No browser UI**; tests use `pytest -m e2e`, assert status codes and response bodies.

### How requests are made

- **`RemoteAPIClient`**: DRF-like surface (`get`/`post`, `.status_code`, `.data`). Anonymous flows use `requests.Session` so **cookies persist** (e.g. storefront cart `sessionid`). Tests do **not** use `@pytest.mark.django_db`: data lives on the API server’s database, not the pytest Django test database.
- Authenticated calls send **Bearer** tokens plus **`X-Workspace-Id` / `X-Workspace-Slug`** (from fixtures).
- If `BASE_URL` ends with **`:8000`**, some paths are **normalized** (e.g. `/api/v1/shop/...` → `/api/v1/...`) to match how routes are mounted on that server.

### Session bootstrap (one pytest session)

1. Read `BASE_URL` and password-related env vars. With **local API host** or `:8000` + superuser env, use the bootstrap account to create workspaces; otherwise register/login to obtain **two workspaces (ws1 / ws2)**.
2. For each workspace, obtain **admin and customer tokens** and customer records for reuse.
3. Test modules use fixtures such as `workspace`, `admin_client`, `customer_client`, `authenticated_client`, and `anonymous_api_client` against the **same API process** (~100+ collected tests by default).

### Coverage by file

| Area | Test file | What it exercises |
|------|-----------|-------------------|
| Accounts & profile | `test_01_registration.py` | Workspace, customer signup, addresses |
| Site & CMS | `test_02_website_setup.py` | Site, pages |
| Store foundation | `test_03_store_setup.py` | Warehouses, stores |
| Catalog (admin) | `test_04_product_mgmt.py` | Categories, products, sales channels |
| Media | `test_05_media_upload.py` | Uploads, product media |
| Warehousing | `test_06_warehouse_setup.py` | Warehouse config, inventory queries |
| Shopping | `test_07_shopping_flow.py` | Add to cart, checkout prep |
| Payments (admin-style) | `test_08_payment_flow.py` | Payment create/process, gift cards |
| Fulfillment | `test_09_fulfillment.py` | Consignments, tracking, returns, package templates, order packages |
| Long journey | `test_10_full_workflow.py` | Full customer journey |
| Support | `test_11_support.py` | Tickets CRUD, list/filter, replies |
| Inbox | `test_12_inbox.py` | Messages, templates, listing |
| Marketing | `test_13_marketing.py` | Campaigns, discount rules, coupons, gift cards, storefront promo payloads |
| Order math | `test_14_order_calculation.py` | Percent/fixed/free shipping, product/category rules, gift cards, **coupon usage limits**, minimum purchase, etc. |
| Input validation | `test_15_input_validation.py` | Invalid/out-of-range payloads for cart, product, invoice, gift card, etc. |
| Multi-tenant isolation | `test_16_workspace_isolation.py` | Cross-workspace read/update/delete must fail |
| Storefront (customer API) | `test_17_storefront_*.py` | Products/categories, filters, anonymous cart, orders, payment intents, **me** (profile, addresses, orders, invoices, …) |
| Storefront inventory | `test_18_storefront_inventory.py` | Multi-warehouse stock display and changes |
| Customer ops | `test_customer_mgmt.py` | Segments, customer tags |
| Sensitive me | `test_z_last_me_sensitive.py` | Password change/reset (**skipped by default**) |

`test_17_storefront.py` is a stub documenting the split; real tests live under `test_17_storefront_*.py`.

### Skips and data prerequisites

- **Skips**: Sensitive me tests—see the env table above; enable explicitly to run them.
- **Data**: At least one active **currency** (fixture validates); most other data is created by tests or the session bootstrap.

## Env variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BASE_URL` | yes | API base URL |
| `BFG2_E2E_SUPERUSER_EMAIL` | optional | Pre-seeded bootstrap user (username or email) when using superuser bootstrap (local API host or `BASE_URL` ending with `:8000`) |
| `BFG2_E2E_SUPERUSER_PASSWORD` | with superuser email | Password for that bootstrap user |
| `BFG2_E2E_AUTH_LOGIN_EMAIL` | optional | If superuser identifier is a **username** but the API token endpoint expects **email**, set the real login email |
| `BFG2_E2E_ADMIN_EMAIL` | when not using superuser bootstrap | Workspace admin email (default `admin@test.com`) |
| `BFG2_E2E_ADMIN_PASSWORD` | when not using superuser bootstrap | Password for workspace admin accounts |
| `BFG2_E2E_CUSTOMER_PASSWORD` | yes | Password for e2e customer accounts (`customer_e2e@test.com`, `customer2_e2e@test.com`, etc.) |
| `BFG2_E2E_TEMP_PASSWORD` | optional | Used only when `test_z_last_me_sensitive.py` change-password tests are enabled |

Sensitive me endpoints (`test_z_last_me_sensitive.py`) are skipped by default.

## Bootstrap behaviour

If both `BFG2_E2E_SUPERUSER_EMAIL` and `BFG2_E2E_SUPERUSER_PASSWORD` are set **and** either `BASE_URL` ends with `:8000` **or** the API host is local (`localhost` / `127.0.0.1` / `::1`), the session uses that account to create workspaces (one token for both workspaces when the API allows).

Otherwise the session registers/logs in `BFG2_E2E_ADMIN_EMAIL` with `BFG2_E2E_ADMIN_PASSWORD` and uses a second admin for the second workspace.

Token login tries `username` and `email` shapes; set `BFG2_E2E_AUTH_LOGIN_EMAIL` if the server requires an email for a username-only superuser.

If token requests fail, confirm the server is up and env credentials match existing users.

### Node.js API (e.g. port 3100)

Use `BASE_URL=http://127.0.0.1:3100` (paths are not rewritten unless the URL ends with `:8000`). From `bfg-server-nodejs`, `npm run e2e` runs resale pytest with the same `BASE_URL` env. Repo root `scripts/e2e-both.sh` sets `BASE_URL` per phase from `PYTHON_API_BASE_URL` / `NODE_API_BASE_URL`.

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

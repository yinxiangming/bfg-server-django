# CLAUDE.md — resale-website/server

Django backend for the Resale Website project, built on the **BFG2 Framework** — a multi-tenant, multi-workspace e-commerce backend library.

## Directory Structure

```
server/
├── apps/                        # Local Django apps (auto-discovered)
│   └── platform -> ../../bfg2/bfg-platform/platform  # Symlink: SaaS platform management app
├── bfg2/                        # BFG2 Framework (git submodule)
│   ├── bfg/                     # Core modules
│   │   ├── docs/                # English agent docs (deployment, architecture, API reference)
│   │   ├── core/                # Agent API, permissions, middleware, PDF
│   │   ├── common/              # Workspace, User, Customer, Address, APIKey, Settings
│   │   ├── web/                 # CMS: pages, posts, media, sites, newsletter, bookings
│   │   ├── shop/                # Products, orders, cart, inventory, subscriptions, returns
│   │   ├── delivery/            # Warehouses, carriers, consignments, tracking, zones
│   │   ├── marketing/           # Campaigns, coupons, referrals, affiliates, gift cards
│   │   ├── finance/             # Payments (Stripe), invoices, wallets, billing cycles
│   │   ├── support/             # Tickets, SLA, knowledge base, feedback
│   │   └── inbox/               # Messages, SMS, notification templates
│   └── tests/                   # BFG2 unit + E2E test suite
├── config/                      # Django project configuration
│   ├── settings.py              # Main settings (all envs)
│   ├── dev.py / prod.py / test.py  # Env-specific overrides
│   ├── urls.py                  # Root URL routing
│   ├── views.py                 # Auth views (register, reset-password, verify-email)
│   ├── serializers.py           # Custom JWT serializer, registration serializers
│   ├── authentication.py        # APIKeyAuthentication + BearerTokenAuthentication
│   ├── social_auth.py           # Google / Facebook / Apple OAuth views
│   ├── celery.py                # Celery app config
│   └── local_apps.py            # Auto-discovery for apps/ directory
├── manage.py
├── requirements.txt             # Production Python dependencies
├── requirements-dev.txt         # Dev/test extras
├── Makefile                     # Common dev commands
└── Dockerfile
```

## Setup & Running

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Required .env vars:
# DATABASE_URL=mysql://user:pass@127.0.0.1:3306/resale
# SECRET_KEY=...
# REDIS_URL=redis://localhost:6379/0
# CELERY_BROKER_URL=redis://localhost:6379/0

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
# Or one-shot init:
make init   # migrate + create workspace + admin + seed data
```

## Key Commands

```bash
make init               # migrate + init workspace, admin, seed data
make install            # pip install -r requirements.txt
make install-bfg2       # create bfg2/venv + install BFG2 deps
make test-bfg2-all      # run all BFG2 tests (pytest)
make test-bfg2-e2e      # run BFG2 E2E tests only
make test-bfg           # run main server tests (manage.py test)
make reset-migrations   # nuke migrations, regenerate, remigrate
make db-create          # create MySQL DB from DATABASE_URL
```

## Running BFG2 Tests

```bash
cd bfg2 && source venv/bin/activate

# All tests:
python -m pytest tests/ -v --tb=short

# Single file:
python -m pytest tests/services/shop/test_order_service.py -v

# Single test:
python -m pytest tests/services/shop/test_order_service.py::TestOrderService::test_create_order -vv

# E2E only:
python -m pytest tests/ -v -m e2e
```

BFG2 tests use in-memory SQLite (configured in `bfg2/tests/settings.py`). Main server uses MySQL.

## Authentication

Three mechanisms (all handled by `config/authentication.py`):

| Method | Header / Token |
|--------|---------------|
| JWT Bearer | `Authorization: Bearer <access_token>` |
| API Key | `X-Api-Key: <key>` + `X-Api-Secret: <secret>` |
| Session | Cookie-based (Django sessions) |

JWT endpoints: `POST /api/v1/auth/token/`, `POST /api/v1/auth/token/refresh/`

Social login: `/api/v1/auth/google/login/`, `/api/v1/auth/facebook/login/`, `/api/v1/auth/apple/login/`

## Multi-tenancy

All models are workspace-scoped. The `WorkspaceMiddleware` resolves the active workspace from:
1. `X-Workspace-Id` request header
2. `workspace_id` query param
3. Domain-based lookup (via `bfg.web.Site`)

Pass `workspace_id` explicitly in API requests when using API keys from a platform context.

## API Docs

- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI schema: `GET /api/schema/`

## Local Apps (apps/)

Apps in `apps/` are auto-discovered by `config/local_apps.py` if they have both `urls.py` and `apps.py`. They register as `apps.<name>` and route at `/api/v1/<name>/`. Override with `LOCAL_APPS=app1,app2` in `.env`.

Currently installed local app:
- **`apps.platform`** (symlink → `bfg-platform/platform`) — SaaS platform management: workspace clusters, feature flags, billing subscriptions, provisioning

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | — | MySQL connection string |
| `SECRET_KEY` | dev-secret | Django secret key |
| `REDIS_URL` | redis://localhost:6379/0 | Redis (cache) |
| `CELERY_BROKER_URL` | redis://localhost:6379/0 | Celery broker |
| `ENV` | dev | Environment (dev/prod) |
| `DEBUG` | True | Django debug mode |
| `FRONTEND_URL` | — | Frontend origin (for email links) |
| `SITE_NAME` | BFG | Site display name |
| `MEDIA_PUBLIC_BASE_URL` | — | Public base URL for media files |
| `BFG_INSTANCE_TYPE` | workspace | Instance type (workspace/platform) |
| `WORKSPACE_API_URL` | http://localhost:8000 | Cross-instance workspace API |
| `PLATFORM_API_KEY` | local-dev-key | Platform-to-workspace auth key |
| `GOOGLE_CLIENT_ID/SECRET` | — | Google OAuth |
| `FACEBOOK_APP_ID/SECRET` | — | Facebook OAuth |
| `APPLE_CLIENT_ID/SECRET/KEY_ID/PRIVATE_KEY` | — | Apple OAuth |

## Skills

- `/bfg-api` — Full reference of all BFG2 models, fields, and API endpoints

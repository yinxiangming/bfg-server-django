# BFG Framework — Workspace Server

Django backend for the BFG open-source e-commerce and SaaS framework. Ships the full BFG module suite (common, shop, web, delivery, marketing, finance, support, inbox) and supports local extension apps via `apps/`.

## Features

- **Multi-workspace** — one database, multiple isolated tenants via `X-Workspace-Id` header
- **JWT auth** — access + refresh tokens, token blacklist
- **Social login** — Google, Apple, Facebook via django-allauth
- **API key auth** — per-workspace or per-integration keys
- **Celery** — background task queue backed by Redis
- **Platform extension** — optional multi-tenant SaaS management layer (embedded or standalone)
- **OpenAPI docs** — Swagger UI at `/api/docs/`, ReDoc at `/api/redoc/`

---

## Quick Start

### Prerequisites

- Python 3.11+
- MySQL 8+ (or PostgreSQL)
- Redis (for Celery)

### Setup

```bash
# 1. Clone and enter project
git clone https://github.com/yinxiangming/bfg-framework.git
cd bfg-framework/src/server

# 2. Create virtualenv
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY at minimum

# 5. Create database
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS mydb CHARACTER SET utf8mb4;"

# 6. Migrate
python manage.py migrate

# 7. Create superuser
python manage.py createsuperuser

# 8. Start server
python manage.py runserver 0.0.0.0:8000
```

API docs: http://localhost:8000/api/docs/

---

## Environment Variables

Copy `.env.example` to `.env`. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | ✅ | Django secret key (generate with `django-admin generate-secret-key`) |
| `DATABASE_URL` | ✅ | MySQL/PostgreSQL connection string |
| `CELERY_BROKER_URL` | ✅ | Redis URL for Celery |
| `CELERY_RESULT_BACKEND` | ✅ | Redis URL for task results |
| `DEBUG` | — | `True` in dev, `False` in production (default: `True`) |
| `FRONTEND_URL` | — | Your frontend origin (used for CORS/redirects) |
| `LOCAL_APPS` | — | Comma-separated app names under `apps/` to load |
| `BFG_INSTANCE_TYPE` | — | `workspace` (default) or `platform` |
| `PLATFORM_WORKSPACE_SLUG` | — | Enables embedded Platform mode (see below) |

See `.env.example` for the full reference including email, social login, Stripe, AI keys, etc.

---

## Local Extension Apps

Place business-specific code under `apps/`:

```
apps/
├── myshop/          ← your custom app
│   ├── apps.py
│   ├── models.py
│   ├── urls.py
│   └── views.py
└── platform/        ← optional Platform extension
```

Then in `.env`:

```env
LOCAL_APPS=myshop,platform
```

Apps are auto-discovered and added to `INSTALLED_APPS`. Their URLs are mounted at `/api/v1/<app_name>/` automatically.

---

## Platform Extension

The Platform extension adds multi-tenant SaaS management: workspace lifecycle, subscriptions, billing, feature flags, SSO, and token exchange.

It runs in two modes:

### Embedded Mode (recommended for self-hosted / small deployments)

One server handles both workspace API and platform admin. One workspace (e.g. `slug=admin`) acts as the management workspace.

```env
LOCAL_APPS=myapp,platform
BFG_INSTANCE_TYPE=workspace
PLATFORM_WORKSPACE_SLUG=admin      # slug of your management workspace
PLATFORM_API_KEY=shared-secret     # for inbound internal calls
```

### Standalone Mode (for large-scale / multi-region)

Platform runs as a separate BFG instance with its own database.

**Workspace server:**
```env
BFG_INSTANCE_TYPE=workspace
PLATFORM_API_KEY=shared-secret
PLATFORM_API_URL=http://platform-server:8011
```

**Platform server (separate deployment):**
```env
BFG_INSTANCE_TYPE=platform
LOCAL_APPS=platform
PLATFORM_API_KEY=shared-secret
WORKSPACE_API_URL=http://workspace-server:8000
```

See the [Platform E2E docs](../../bfg-server-test-e2e/PLATFORM_E2E.md) for full setup and test instructions.

---

## Running Celery

```bash
# Worker
celery -A config.celery worker -l info

# Beat scheduler (periodic tasks)
celery -A config.celery beat -l info

# Or combined (dev only)
celery -A config.celery worker --beat -l info
```

---

## Email in Development

Use [Mailpit](https://mailpit.axllent.org/) (recommended) or MailHog to catch all outgoing emails:

```bash
# Mailpit
brew install mailpit
mailpit
# Web UI: http://localhost:8025, SMTP: localhost:1025
```

`.env`:
```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=127.0.0.1
EMAIL_PORT=1025
EMAIL_USE_TLS=False
```

---

## API Reference

| Endpoint | Description |
|----------|-------------|
| `GET /api/docs/` | Swagger UI |
| `GET /api/redoc/` | ReDoc |
| `POST /api/v1/auth/token/` | Get JWT (`email` + `password`) |
| `POST /api/v1/auth/token/refresh/` | Refresh JWT |
| `POST /api/v1/auth/register/` | Register new user |
| `GET /api/v1/workspaces/` | List workspaces for current user |
| `POST /api/v1/workspaces/` | Create workspace |
| `GET /api/v1/customers/` | Customer list (workspace-scoped) |

All workspace-scoped endpoints require `X-Workspace-Id: <id>` header.

Authentication:
```
Authorization: Bearer <access_token>
```

---

## E2E Testing

The project has a separate HTTP end-to-end test suite at `bfg-server-test-e2e/`. Tests run against a live server — no mocking.

```bash
cd ../../bfg-server-test-e2e
pip install -r requirements.txt
cp .env.example .env    # set BASE_URL, credentials
pytest e2e/ -m e2e -v
```

See [bfg-server-test-e2e/README.md](../../bfg-server-test-e2e/README.md) for details.

---

## Project Structure

```
src/server/
├── config/                 # Django settings, URLs, auth, WSGI
│   ├── settings.py         # Main settings (reads from .env)
│   ├── dev.py              # Development settings override
│   ├── urls.py             # Root URL config
│   ├── authentication.py   # Custom JWT + API key authentication
│   ├── local_apps.py       # Auto-discovery of apps/ directory
│   └── views.py            # Internal endpoints (provision-user, etc.)
├── apps/                   # Local extension apps (git-ignored or custom)
│   ├── nexus/              # Example app
│   └── platform/           # Platform extension (optional)
├── bfg2/                   # BFG2 core modules (bfg/ package)
│   └── bfg/
│       ├── common/         # Users, Workspaces, StaffMembers, API keys
│       ├── shop/           # Products, Orders, Cart, Subscriptions
│       ├── delivery/       # Warehouses, Carriers, Consignments
│       ├── finance/        # Payments, Invoices, Wallets
│       ├── marketing/      # Campaigns, Coupons, Gift cards
│       ├── support/        # Tickets
│       ├── inbox/          # Notifications, Message templates
│       └── web/            # Website/CMS, Bookings
├── media/                  # Uploaded files (local dev)
├── templates/              # Django HTML templates
├── manage.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── Makefile
```

---

## Production Deployment

1. Set `DEBUG=False`, `SECRET_KEY` to a strong random value
2. Set `ALLOWED_HOSTS` in settings or use a reverse proxy (nginx)
3. Use `gunicorn` or `uvicorn`:
   ```bash
   gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4
   # or
   uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 4
   ```
4. Serve static files via WhiteNoise (already configured) or nginx
5. Use `MEDIA_PUBLIC_BASE_URL` to point media URLs at a CDN
6. Run Celery worker and beat as separate processes/services

---

## License

MIT

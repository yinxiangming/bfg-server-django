# channels-server

Django extension for multi-channel product listing (TradeMe + Shopify).

## Setup

```bash
# Link extension into server apps (run from nexus root)
bash scripts/link-nexus-extensions.sh

# Run migrations
python manage.py migrate

# Verify it loaded
python manage.py shell -c "from apps.channels.models import ExternalChannel; print('OK')"
```

## Environment

No extra env vars required beyond the base server config.

Optional:
```
# Use sandbox for TradeMe (set per-channel via config.sandbox=true)
```

## API Endpoints

All endpoints live at `/api/v1/channels/`.

| Method | URL | Description |
|--------|-----|-------------|
| GET/POST | `/channels/` | List / create channels |
| GET/PATCH/DELETE | `/channels/{id}/` | Retrieve / update / delete |
| POST | `/channels/{id}/validate/` | Test credentials |
| POST | `/channels/{id}/publish/{product_id}/` | Publish product |
| GET | `/channels/{id}/listings/` | Listings for this channel |
| GET | `/channels/{id}/field-spec/` | Field mapping spec |
| GET | `/listings/?channel=&product=` | Filtered listings |
| POST | `/listings/{id}/end/` | End a listing |
| POST | `/listings/{id}/relist/` | Relist |
| GET | `/feedback/?channel=` | Feedback |
| POST | `/feedback/{id}/reply/` | Reply to feedback |
| GET | `/questions/?channel=` | Questions |
| POST | `/questions/{id}/answer/` | Answer a question |
| GET/POST | `/faq-rules/?channel=` | FAQ auto-answer rules |
| POST | `/ai/analyze/` | OpenAI requirement analysis |

## TradeMe Credentials

```json
{
  "consumer_key": "...",
  "consumer_secret": "...",
  "oauth_token": "...",
  "oauth_token_secret": "..."
}
```

Config options:
```json
{
  "sandbox": true,
  "default_duration_days": 7,
  "default_category_id": "0001-",
  "auto_publish": true,
  "auto_relist": true,
  "ai_auto_answer": false,
  "answer_delay_minutes": 30,
  "shipping_options": []
}
```

## Shopify Credentials

```json
{
  "shop_domain": "mystore.myshopify.com",
  "api_key": "...",
  "api_password": "..."
}
```

## Celery Tasks

Periodic tasks are scheduled via `CELERY_BEAT_SCHEDULE` in `config/settings.py`:

- **Every hour** — fetch feedback for all active listings
- **Every 15 min** — fetch buyer questions + auto-answer via FAQ rules
- **Daily 2 AM** — relist expiring listings (`auto_relist=true`)

Start Celery worker + beat:
```bash
celery -A config worker -l info
celery -A config beat -l info
```

## Running E2E Tests

```bash
cd /path/to/nexus
PYTHONPATH=src/server:src/server/bfg2:extensions \
  DJANGO_SETTINGS_MODULE=tests.e2e.settings \
  src/server/.venv/bin/python -m pytest extensions/tests/e2e/test_channels_e2e.py -v
```

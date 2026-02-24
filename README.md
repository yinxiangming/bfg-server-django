# BFG Framework — Server (Django)

Core-only backend: BFG modules (common, shop, web, delivery, marketing, finance, support, inbox). No business-specific `apps.*` modules.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env  # then edit .env
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

## Environment

See `.env.example` for `DATABASE_URL`, `SECRET_KEY`, `REDIS_URL`, etc. API docs: `/api/docs/` and `/api/redoc/`.

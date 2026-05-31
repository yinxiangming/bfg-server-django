"""
Production settings
"""
import os
from .settings import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# Sentry SDK is initialised in config/settings.py (the active settings module),
# gated on SENTRY_DSN. This line is kept for ``bfg_prod_check`` compatibility.
SENTRY_DSN = os.environ.get('SENTRY_DSN', '').strip()

# Shared Django cache (workspace resolution, storefront JSON). Prefer Redis in prod
# so all Gunicorn workers and ``dokku run`` see the same keys; use a DB index other
# than Celery's (e.g. Celery ``/0``, cache ``/1``).
_DJANGO_CACHE_URL = os.environ.get('DJANGO_CACHE_URL', '').strip()
if _DJANGO_CACHE_URL:
    _cache_key_prefix = os.environ.get('DJANGO_CACHE_KEY_PREFIX', 'bfg').strip() or 'bfg'
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _DJANGO_CACHE_URL,
            'KEY_PREFIX': _cache_key_prefix,
        }
    }

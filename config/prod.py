"""
Production settings
"""
import os
from .settings import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# Exposed for ``bfg_prod_check`` and optional Sentry SDK wiring (env set on Dokku).
SENTRY_DSN = os.environ.get('SENTRY_DSN', '').strip()

# Sentry error monitoring. Initialised only when SENTRY_DSN is set (via Dokku config),
# so non-Sentry deploys are unaffected. SENTRY_ENVIRONMENT distinguishes UAT vs prod;
# SENTRY_TRACES_SAMPLE_RATE (0..1) enables performance tracing (default off = errors only).
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get('SENTRY_ENVIRONMENT', 'production').strip() or 'production',
        # Add data like request headers and IP for users; see
        # https://docs.sentry.io/platforms/python/data-management/data-collected/
        send_default_pii=True,
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0') or 0),
    )

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

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

# Cache: CACHES is configured in config/settings.py from DJANGO_CACHE_URL so that
# staging shares production's backend. bfg_prod_check enforces that prod actually
# sets it — a LocMemCache here means workers silently disagree.

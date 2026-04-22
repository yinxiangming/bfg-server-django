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

# Production-specific settings can be added here

"""
Django settings for running tests.
"""

import os
from pathlib import Path

import sys
BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = BASE_DIR.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SERVER_DIR))

# Test-only; never use in production. Override via env in CI if required.
SECRET_KEY = os.environ.get('SECRET_KEY', 'test-insecure-do-not-use-in-production')

DEBUG = True

# Match config/settings.py's env switch so SecurityHeadersMiddleware
# picks the Report-Only CSP variant under test (per Phase-0 PR-02).
ENV = 'test'
IS_PROD = False

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'dj_rest_auth',
    'dj_rest_auth.registration',
    'rest_framework.authtoken',
    # BFG Modules
    'bfg.common',
    'bfg.core',
    'bfg.web',
    'bfg.shop',
    'bfg.delivery',
    'bfg.finance',
    'bfg.support',
    'bfg.inbox',
    'bfg.marketing',
    'bfg.platform',
    # Test-only app (Phase-0 PR-01): provides a synthetic model the
    # tenant_isolation suite uses to exercise TenantScopedModel.
    'tests.tenant_isolation.apps.TenantIsolationTestsConfig',
]

# Test-only app has no migrations directory; let Django create its
# table via syncdb during test DB setup.
MIGRATION_MODULES = {
    'tenant_isolation_tests': None,
}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be first so OPTIONS gets CORS headers
    'django.middleware.security.SecurityMiddleware',
    # Phase-0 PR-02: exercise SecurityHeadersMiddleware in tests too so
    # header/CSP assertions (tests/security/) run against the real code.
    'bfg.common.security_headers.SecurityHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Phase-0 PR-04: was ``bfg.core.middleware.WorkspaceMiddleware``
    # (legacy 11-line shim); swap in the real strict-mode middleware so
    # tests exercise the production behaviour.
    'bfg.common.middleware.WorkspaceMiddleware',
]

ROOT_URLCONF = 'tests.urls'

# CORS: allow Next.js frontend (dev). When using tests.settings for runserver.
# Use allow-all in dev to avoid origin/header mismatches; restrict in production.
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
# Extend default headers with custom ones (x-forwarded-host, x-workspace-id)
from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + [
    'accept-language',
    'x-forwarded-host',
    'x-workspace-id',
    # Guest cart identity, read by StorefrontCartViewSet._get_or_create_cart. The
    # storefront reaches the API cross-site, so the session cookie never arrives and
    # this header is the only thing keeping a guest's cart from resetting per request.
    'x-bfg-cart-session',
    'x-cart-id',
]

# Phase-0 PR-02: CSP origin lists consumed by SecurityHeadersMiddleware.
# Keep defaults tight in tests so assertions have a stable baseline.
CSP_FRONTEND_ORIGINS = ["'self'"]
CSP_API_ORIGINS = ["'self'"]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# DRF Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
}

# BFG Settings
BFG2_SETTINGS = {
    'ENABLE_BATCH_MANAGEMENT': True,
}

# Static files
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'tests/media')

# Password validation
AUTH_PASSWORD_VALIDATORS = []

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# User model
AUTH_USER_MODEL = 'common.User'

# Celery: Run tasks synchronously in tests (EAGER mode)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

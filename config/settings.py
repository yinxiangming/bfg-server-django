"""
Django settings for BFG Framework (open-source core).

Core-only build: no apps.* (business modules). Use this for the public repo.
"""

import json
import os
import sys
from datetime import timedelta
from dotenv import load_dotenv
import dj_database_url

from config.local_apps import get_local_app_dotted_names

# Project root (src/server): must be defined before load_dotenv so .env is found regardless of cwd.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables from src/server/.env (not only from process cwd).
ENV = os.environ.get('ENV', 'dev').lower().strip()
if ENV == 'local' or ENV == 'dev':
    load_dotenv(os.path.join(BASE_DIR, '.env'))

# ─── Environment helpers ──────────────────────────────────────────────
# Single source of truth for "are we running in production?". Used by
# every hardening flag below so a single env change flips them together.
IS_PROD = ENV == 'prod'


def _env_bool(name, default):
    """Parse a truthy env var, returning ``default`` when unset."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name, default=None):
    """Parse a comma-separated env var into a ``list[str]``."""
    raw = os.environ.get(name, '')
    if not raw.strip():
        return list(default or [])
    return [item.strip() for item in raw.split(',') if item.strip()]

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'
TESTING = sys.argv[1:2] == ['test']

# Cross-instance configuration
BFG_INSTANCE_TYPE = os.environ.get('BFG_INSTANCE_TYPE', 'workspace')
WORKSPACE_API_URL = os.environ.get('WORKSPACE_API_URL', 'http://localhost:8000')
PLATFORM_API_URL = os.environ.get('PLATFORM_API_URL', '')
PLATFORM_API_KEY = os.environ.get('PLATFORM_API_KEY', '')

# Embedded Platform mode: a single BFG instance acts as both Platform and Workspace.
PLATFORM_WORKSPACE_SLUG = os.environ.get('PLATFORM_WORKSPACE_SLUG', '')
PLATFORM_EMBEDDED = bool(PLATFORM_WORKSPACE_SLUG) and BFG_INSTANCE_TYPE == 'workspace'

# If True, Django superuser passes tenant permission checks (IsWorkspaceStaff/Admin) without StaffMember.
# Set False for strict multi-tenant: superuser must have a StaffMember row per workspace (or use Django admin only).
# Default: off in production, on everywhere else. Explicit env var still wins.
BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS = _env_bool(
    'BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS',
    default=not IS_PROD,
)

ALLOWED_HOSTS = ['*']

# ─── Error monitoring (Sentry) ────────────────────────────────────────
# Initialised only when SENTRY_DSN is set (per-app Dokku config), so dev and
# non-Sentry deploys are unaffected. SENTRY_ENVIRONMENT distinguishes UAT vs
# prod (falls back to ENV); SENTRY_TRACES_SAMPLE_RATE (0..1) enables tracing
# (default off = errors only). Skipped under `manage.py test`.
SENTRY_DSN = os.environ.get('SENTRY_DSN', '').strip()
if SENTRY_DSN and not TESTING:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get('SENTRY_ENVIRONMENT', '').strip() or ENV or 'production',
        # Add data like request headers and IP for users; see
        # https://docs.sentry.io/platforms/python/data-management/data-collected/
        send_default_pii=True,
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0') or 0),
    )

# ─── Server-side Google Analytics 4 (Measurement Protocol) ────────────
# A JSON object mapping GA4 measurement id -> Measurement Protocol api_secret,
# e.g. {"G-XXXXXXXXXX": "…"}. Keyed by measurement id rather than workspace id so
# the secret follows the GA4 property, and because the measurement id is what
# bfg.core.analytics already resolves from the workspace's settings.
#
# It is *not* stored per workspace in the database: SettingsSerializer echoes
# `custom_settings` wholesale, which would expose this write credential to every
# workspace admin. Unset simply disables server-side reporting.
try:
    GA4_MP_API_SECRETS = json.loads(os.environ.get('GA4_MP_API_SECRETS', '') or '{}')
    if not isinstance(GA4_MP_API_SECRETS, dict):
        raise ValueError('GA4_MP_API_SECRETS must be a JSON object')
except (ValueError, TypeError) as exc:
    # Never take the whole app down over an analytics misconfiguration — but say so
    # loudly, because the symptom otherwise is silently missing data.
    import warnings

    warnings.warn(f'Ignoring malformed GA4_MP_API_SECRETS: {exc}')
    GA4_MP_API_SECRETS = {}

# Application definition (BFG core only; no apps.* business modules)
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party
    'corsheaders',
    'rest_framework',
    'drf_spectacular',
    'anymail',
    
    # Social Login
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.apple',
    'allauth.socialaccount.providers.facebook',
    'rest_framework_simplejwt.token_blacklist',

    # BFG2 modules (bfg2 must be in Python path - added in manage.py)
    'bfg.core',
    'bfg.common',
    'bfg.web',
    'bfg.shop',
    'bfg.delivery',
    'bfg.marketing',
    'bfg.finance',
    'bfg.support',
    'bfg.inbox',
    'bfg.platform',
    # Local apps (from env LOCAL_APPS or auto-discovered from apps dir)
    *get_local_app_dotted_names(),
    # Project hooks (startup logging, etc.); must be last so ready() sees all apps
    'config.apps.Config',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # Phase-0 PR-02: defence-in-depth response headers (X-Frame-Options,
    # Referrer-Policy, Permissions-Policy, CSP). Placed right after
    # Django's SecurityMiddleware so HSTS + our static headers co-exist.
    'bfg.common.security_headers.SecurityHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'bfg.common.middleware.WorkspaceMiddleware',
    'bfg.common.middleware.AuditLogMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
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

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'sql_mode': 'traditional',
        }
    }
}
db_from_env = dj_database_url.config(conn_max_age=500)
if db_from_env:
    DATABASES['default'].update(db_from_env)

if not DATABASES['default'].get('ENGINE', '').endswith('.mysql'):
    DATABASES['default'].pop('OPTIONS', None)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'common.User'

# django-allauth (social login)
SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_AUTO_SIGNUP = True
# Skip intermediate "Sign in with Google" page; GET to login URL redirects directly to provider
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.environ.get('GOOGLE_CLIENT_ID', ''),
            'secret': os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
    },
    'facebook': {
        'APP': {
            'client_id': os.environ.get('FACEBOOK_APP_ID', ''),
            'secret': os.environ.get('FACEBOOK_APP_SECRET', ''),
        },
        'SCOPE': ['email', 'public_profile'],
    },
    'apple': {
        'APP': {
            'client_id': os.environ.get('APPLE_CLIENT_ID', ''),
            'secret': os.environ.get('APPLE_SECRET', ''),
            'key': os.environ.get('APPLE_KEY_ID', ''),
            'certificate_key': os.environ.get('APPLE_PRIVATE_KEY', ''),
        },
    },
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en'
LANGUAGES = [('en', 'English'), ('zh-hans', '简体中文')]
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

# ─── Media storage ──────────────────────────────────────────────────────
# Set AWS_STORAGE_BUCKET_NAME to route uploads to S3; otherwise, files are
# written to MEDIA_ROOT on the local filesystem and served by Django.
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '').strip()
USE_S3_MEDIA = bool(AWS_STORAGE_BUCKET_NAME)

MEDIA_ROOT = os.path.join(BASE_DIR, 'media')  # always defined; used as local fallback / dev

if USE_S3_MEDIA:
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'ap-southeast-2').strip()
    # CloudFront / custom CDN domain (without scheme), e.g. cdn.preloved.kiwi.
    AWS_S3_CUSTOM_DOMAIN = os.environ.get('AWS_S3_CUSTOM_DOMAIN', '').strip() or None
    # Key prefix inside the bucket, e.g. 'nexus/prod'. Lets several projects and
    # environments share one bucket + CDN without colliding: production and UAT
    # get disjoint prefixes, so a UAT upload or delete can never touch prod media.
    AWS_LOCATION = os.environ.get('AWS_LOCATION', '').strip().strip('/')
    # Boto3 picks up AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from env automatically.

    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {
                'bucket_name': AWS_STORAGE_BUCKET_NAME,
                'region_name': AWS_S3_REGION_NAME,
                'custom_domain': AWS_S3_CUSTOM_DOMAIN,
                'location': AWS_LOCATION,
                'file_overwrite': False,         # never silently clobber an existing key
                'querystring_auth': False,       # bucket is public-read; no signed URLs
                'default_acl': None,             # rely on bucket policy
                'object_parameters': {'CacheControl': 'public, max-age=31536000, immutable'},
            },
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }
    # MEDIA_URL must carry AWS_LOCATION too: S3Storage.url() prepends the prefix
    # itself, but bfg.common.serializers builds URLs as MEDIA_URL + file.name and
    # would otherwise point one directory above every object.
    _media_host = AWS_S3_CUSTOM_DOMAIN or f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com'
    MEDIA_URL = f'https://{_media_host}/' + (f'{AWS_LOCATION}/' if AWS_LOCATION else '')

    # Private bucket for sensitive media (package photos, customs docs, payment
    # proofs). Served via short-lived signed (SigV4) URLs and never through the
    # public CDN, so objects are not world-readable. Defaults to the main bucket
    # when no dedicated private bucket is configured; set a separate private
    # bucket in production for true isolation. See bfg.common.storage.
    AWS_PRIVATE_STORAGE_BUCKET_NAME = (
        os.environ.get('AWS_PRIVATE_STORAGE_BUCKET_NAME', '').strip() or AWS_STORAGE_BUCKET_NAME
    )
    AWS_PRIVATE_URL_EXPIRE = int(os.environ.get('AWS_PRIVATE_URL_EXPIRE', '3600'))  # signed-URL TTL, seconds
    STORAGES['media_private'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': AWS_PRIVATE_STORAGE_BUCKET_NAME,
            'region_name': AWS_S3_REGION_NAME,
            'location': AWS_LOCATION,            # same per-environment namespacing
            'querystring_auth': True,            # SigV4-signed, expiring URLs
            'querystring_expire': AWS_PRIVATE_URL_EXPIRE,
            'default_acl': 'private',
            'file_overwrite': False,
            'custom_domain': None,               # never serve private media via the public CDN
        },
    }
else:
    MEDIA_URL = '/media/'
    # Local dev: sensitive media falls back to the same filesystem storage; no
    # signing is applied (see bfg.common.storage.private_media_storage).
    AWS_PRIVATE_STORAGE_BUCKET_NAME = ''
    AWS_PRIVATE_URL_EXPIRE = 3600
    AWS_LOCATION = ''

# Absolute API/site origin for media URLs when storage returns relative paths (e.g. GitHub issue embeds).
MEDIA_PUBLIC_BASE_URL = os.environ.get('MEDIA_PUBLIC_BASE_URL', '').strip().rstrip('/')

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'config.authentication.APIKeyAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'config.authentication.BearerTokenAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'config.pagination.StandardPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# WeChat mini-program login (apps.wechat_identity). The wxstore cutover reuses
# the legacy mini-program's AppID, so the openids backfilled by the legacy
# importer match what jscode2session returns and returning members log in to
# their existing account.
WECHAT_MINIPROGRAM_APPID = os.environ.get('WECHAT_MINIPROGRAM_APPID', '').strip()
WECHAT_MINIPROGRAM_APPSECRET = os.environ.get('WECHAT_MINIPROGRAM_APPSECRET', '').strip()

# Google Maps, server side (apps.geo). Address suggestions and reverse geocoding
# run here rather than in the client because the mini-program cannot load Google's
# JavaScript SDK, and a key shipped in a mini-program bundle is a key anyone can
# extract and spend. Restrict this key to the Places and Geocoding APIs, and to the
# server's IP — it is never sent to a client. Which workspaces may use it, and the
# country each is restricted to, is a per-workspace setting, not an env var.
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()

# JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_REFRESH_SERIALIZER': 'config.serializers.CustomTokenRefreshSerializer',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'BFG Framework API',
    'DESCRIPTION': 'BFG open-source e-commerce and SaaS backend API',
    'VERSION': '1.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
    },
}

# ─── CORS ─────────────────────────────────────────────────────────────
# Production: explicit whitelist only. Everywhere else: allow all so
# local Next.js dev servers and Storybook can hit the API without ops
# overhead. Every env can still override via CORS_ALLOW_ALL_ORIGINS.
CORS_ALLOW_ALL_ORIGINS = _env_bool('CORS_ALLOW_ALL_ORIGINS', default=not IS_PROD)
CORS_ALLOWED_ORIGINS = _env_list('CORS_ALLOWED_ORIGINS')
CORS_ALLOWED_ORIGIN_REGEXES = _env_list('CORS_ALLOWED_ORIGIN_REGEXES')
CORS_ALLOW_CREDENTIALS = True
# Private-network requests stay on in non-prod so engineers can reach
# the API from the local network; prod should never need this.
CORS_ALLOW_PRIVATE_NETWORK = _env_bool('CORS_ALLOW_PRIVATE_NETWORK', default=not IS_PROD)
# x-bfg-cart-session / x-cart-id carry guest-cart identity. The storefront and the
# API sit on different registrable domains (geeker.co.nz vs surlex.co.nz), so the
# sessionid cookie is cross-site and SameSite=Lax keeps the browser from ever sending
# it back — every request would otherwise land on a brand-new empty cart. Leaving
# these two out of the allowlist fails the preflight and reinstates that bug.
CORS_ALLOW_HEADERS = [
    'accept', 'accept-language', 'accept-encoding', 'authorization',
    'content-type', 'dnt', 'origin', 'user-agent', 'x-csrftoken',
    'x-requested-with', 'x-workspace-id', 'x-forwarded-host',
    'x-api-key', 'x-api-secret', 'x-bfg-cart-session', 'x-cart-id',
]
CORS_EXPOSE_HEADERS = [
    'X-Request-Id',
    'X-RateLimit-Limit',
    'X-RateLimit-Remaining',
    'X-RateLimit-Reset',
]

# ─── Transport / cookie security ──────────────────────────────────────
# Prod flips every hardening flag on; dev/staging stays lenient so
# developers don't have to run the whole stack over HTTPS.
if IS_PROD:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
else:
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0

# ─── Content Security Policy origin lists ─────────────────────────────
# Consumed by bfg.common.security_headers.SecurityHeadersMiddleware.
# CSP_API_ORIGINS widens ``connect-src``; CSP_FRONTEND_ORIGINS is
# declared here for a follow-up PR that wires it into frame-src /
# form-action once the frontend deploy topology is finalised.
CSP_FRONTEND_ORIGINS = _env_list('CSP_FRONTEND_ORIGINS', default=["'self'"])
CSP_API_ORIGINS = _env_list('CSP_API_ORIGINS', default=["'self'"])

# ─── Shared cache ─────────────────────────────────────────────────────
# Workspace resolution and the public storefront JSON are cached per workspace.
# Point DJANGO_CACHE_URL at Redis in any multi-process deployment: without it
# Django falls back to a per-process LocMemCache, so each Gunicorn worker keeps
# its own copy and an invalidation issued by one worker (or by ``dokku run``)
# never reaches the others. Use a DB index other than Celery's — e.g. Celery on
# ``/0``, cache on ``/1``.
_DJANGO_CACHE_URL = os.environ.get('DJANGO_CACHE_URL', '').strip()
if _DJANGO_CACHE_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _DJANGO_CACHE_URL,
            'KEY_PREFIX': os.environ.get('DJANGO_CACHE_KEY_PREFIX', 'bfg').strip() or 'bfg',
        }
    }

# How long workspace-scoped cache entries live, in seconds. See
# bfg.common.cache_policy for what this bounds.
BFG_CACHE_TTL = int(os.environ.get('BFG_CACHE_TTL', '300') or '300')

# Celery
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Email
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '1025') or '1025')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'False').lower() == 'true'
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@example.com')

# Anymail (Mailgun) — activated when EMAIL_BACKEND is set to the anymail backend.
# Keep the default (smtp) for callers that haven't opted in; UAT / prod can flip this
# via env without touching code.
ANYMAIL = {
    'MAILGUN_API_KEY': os.environ.get('MAILGUN_API_KEY', ''),
    'MAILGUN_SENDER_DOMAIN': os.environ.get('MAILGUN_SENDER_DOMAIN', ''),
    # EU users: set MAILGUN_API_URL=https://api.eu.mailgun.net/v3 via env. US default works unset.
    'MAILGUN_API_URL': os.environ.get('MAILGUN_API_URL', 'https://api.mailgun.net/v3'),
}

# Onboarding / auth flow toggles
EMAIL_VERIFICATION_REQUIRED = os.environ.get('EMAIL_VERIFICATION_REQUIRED', 'true').lower() in ('1', 'true', 'yes')
ONBOARDING_PROVISION_ON_REGISTER = os.environ.get('ONBOARDING_PROVISION_ON_REGISTER', 'true').lower() in ('1', 'true', 'yes')
FRONTEND_EMAIL_CONFIRM_PATH = os.environ.get('FRONTEND_EMAIL_CONFIRM_PATH', '/auth/verify-email').strip() or '/auth/verify-email'

# Frontend URL and site name (from env)
FRONTEND_URL = os.environ.get('FRONTEND_URL', '')
# Fallback for POST /platform/auth/sso/start/ when WorkspacePlatformProfile.custom_domain is empty.
# Prefer setting custom_domain (or cluster.frontend_base_url) per workspace in production.
WORKSPACE_FRONTEND_URL = os.environ.get('WORKSPACE_FRONTEND_URL', '').strip()
SITE_NAME = os.environ.get('SITE_NAME', 'BFG')

# Staff invitations: default TTL in hours (used when admin doesn't override per-invite).
INVITATION_EXPIRY_HOURS = int(os.environ.get('INVITATION_EXPIRY_HOURS', '48'))

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {'handlers': ['console'], 'level': 'DEBUG' if DEBUG else 'INFO'},
}

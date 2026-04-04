"""
Resolve DJANGO_SETTINGS_MODULE from ENV (shared by manage.py, wsgi, asgi, celery).
"""
import os

_ENV_TO_SETTINGS_MODULE = {
    'prod': 'config.prod',
    'test': 'config.test',
    'dev': 'config.dev',
    'local': 'config.dev',
}


def resolve_django_settings_module(env: str | None = None) -> str:
    """Return settings module dotted path for the given or current ENV."""
    if env is None:
        env = os.getenv('ENV', 'dev')
    return _ENV_TO_SETTINGS_MODULE.get(env, 'config.settings')


def setdefault_django_settings_module() -> str:
    """Set DJANGO_SETTINGS_MODULE if unset; return the resolved module path."""
    module = resolve_django_settings_module()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', module)
    return module

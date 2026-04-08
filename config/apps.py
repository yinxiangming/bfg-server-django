"""Project AppConfig: startup diagnostics."""

import logging
import os
import sys

from django.apps import AppConfig, apps

logger = logging.getLogger(__name__)


def _should_log_installed_apps() -> bool:
    """Avoid duplicate lines from runserver autoreloader parent; allow real server processes."""
    argv0 = sys.argv[0] if sys.argv else ''
    if argv0.endswith('manage.py') or os.path.basename(argv0) == 'manage.py':
        if 'runserver' not in sys.argv:
            return False
        return os.environ.get('RUN_MAIN') == 'true'
    return True


class Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'config'
    verbose_name = 'Project'

    def ready(self) -> None:
        if not _should_log_installed_apps():
            return
        names = sorted(ac.name for ac in apps.get_app_configs())
        local = [n for n in names if n.startswith('apps.')]
        logger.info(
            'Django installed apps (%d); local apps.* (%d): %s',
            len(names),
            len(local),
            ', '.join(local) if local else '(none)',
        )
        logger.info('Installed apps:\n%s', '\n'.join(f'  {n}' for n in names))

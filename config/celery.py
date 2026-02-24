"""
Celery configuration for Django project.
"""

import os
import sys
from pathlib import Path
from celery import Celery

# Add bfg2 to Python path (same as manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent
bfg2_path = BASE_DIR / 'bfg2'
if str(bfg2_path) not in sys.path:
    sys.path.insert(0, str(bfg2_path))

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Explicitly load tasks from plugin apps (apps.*) so worker registers their @shared_task.
try:
    from django.conf import settings as django_settings
    for app_name in getattr(django_settings, 'INSTALLED_APPS', []):
        if isinstance(app_name, str) and app_name.startswith('apps.'):
            try:
                __import__(f'{app_name}.tasks')
            except ImportError:
                pass
except Exception:
    pass

# Handle EAGER mode for testing
# This must be done after config_from_object to ensure settings are loaded
try:
    from django.conf import settings
    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        app.conf.task_always_eager = True
        app.conf.task_eager_propagates = True
        # Override broker and result backend for testing
        if hasattr(settings, 'CELERY_BROKER_URL') and 'memory://' in settings.CELERY_BROKER_URL:
            app.conf.broker_url = settings.CELERY_BROKER_URL
        if hasattr(settings, 'CELERY_RESULT_BACKEND') and 'memory://' in settings.CELERY_RESULT_BACKEND:
            app.conf.result_backend = settings.CELERY_RESULT_BACKEND
except ImportError:
    # Django not initialized yet, will be set later
    pass


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

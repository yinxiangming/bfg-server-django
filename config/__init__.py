import sys
from pathlib import Path

# Add bfg2 to Python path (same as manage.py and celery.py)
BASE_DIR = Path(__file__).resolve().parent.parent
bfg2_path = BASE_DIR / 'bfg2'
if str(bfg2_path) not in sys.path:
    sys.path.insert(0, str(bfg2_path))

import pymysql

# pymysql.version_info = (1, 4, 13, "final", 0)  # change this to your pymysql version
pymysql.install_as_MySQLdb()

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from .celery import app as celery_app

# Reconfigure Celery app if Django settings are available
# This ensures test settings (EAGER mode) are applied
try:
    from django.conf import settings
    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        if hasattr(settings, 'CELERY_BROKER_URL') and 'memory://' in settings.CELERY_BROKER_URL:
            celery_app.conf.broker_url = settings.CELERY_BROKER_URL
        if hasattr(settings, 'CELERY_RESULT_BACKEND') and 'memory://' in settings.CELERY_RESULT_BACKEND:
            celery_app.conf.result_backend = settings.CELERY_RESULT_BACKEND
except:
    # Django not initialized yet, will be set when settings are loaded
    pass

__all__ = ('celery_app',)

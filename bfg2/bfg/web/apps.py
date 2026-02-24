# -*- coding: utf-8 -*-
from django.apps import AppConfig


class WebConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.web'
    verbose_name = 'BFG Web & CMS'
    
    def ready(self):
        """Import signals and event handlers when app is ready."""
        try:
            import bfg.web.signals  # noqa
        except ImportError:
            pass
        try:
            import bfg.web.handlers  # noqa
        except ImportError:
            pass

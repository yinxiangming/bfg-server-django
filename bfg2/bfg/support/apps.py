# -*- coding: utf-8 -*-
from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.support'
    verbose_name = 'BFG Support & Help Desk'
    
    def ready(self):
        """Import signals when app is ready."""
        try:
            import bfg.support.signals  # noqa
        except ImportError:
            pass

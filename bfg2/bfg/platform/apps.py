# -*- coding: utf-8 -*-
from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bfg.platform"
    verbose_name = "BFG Platform"

    def ready(self):
        """Import signals when app is ready."""
        try:
            import bfg.platform.signals  # noqa
        except ImportError:
            pass

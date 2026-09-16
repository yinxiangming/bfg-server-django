# -*- coding: utf-8 -*-
from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bfg.platform"
    verbose_name = "BFG Platform"

    def ready(self):
        """Import signals and event handlers when app is ready."""
        try:
            import bfg.platform.signals  # noqa
        except ImportError:
            pass

        # Renewing what a paid bill bought; see bfg.platform.handlers.
        try:
            import bfg.platform.handlers  # noqa
        except ImportError:
            pass

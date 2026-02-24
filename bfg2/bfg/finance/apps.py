# -*- coding: utf-8 -*-
from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.finance'
    verbose_name = 'BFG Finance & Billing'
    
    def ready(self):
        """Import signals and event handlers when app is ready."""
        try:
            import bfg.finance.signals  # noqa
        except ImportError:
            pass
        
        # Register event handlers for payment notifications
        try:
            import bfg.finance.handlers  # noqa
        except ImportError:
            pass

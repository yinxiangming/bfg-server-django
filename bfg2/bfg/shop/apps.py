# -*- coding: utf-8 -*-
from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.shop'
    verbose_name = 'BFG Shop & E-commerce'
    
    def ready(self):
        """Import signals and event handlers when app is ready."""
        try:
            import bfg.shop.signals  # noqa
        except ImportError:
            pass
        
        # Register event handlers for order notifications
        try:
            import bfg.shop.handlers  # noqa
        except ImportError:
            pass

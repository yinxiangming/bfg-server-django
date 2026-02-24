# -*- coding: utf-8 -*-
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.common'
    verbose_name = 'BFG Common'
    
    def ready(self):
        """Import signals when app is ready."""
        try:
            import bfg.common.signals  # noqa
        except ImportError:
            pass
        
        # Register customer condition fields
        try:
            from bfg.core.condition_engine import get_condition_engine
            from bfg.common.condition_fields import CustomerFieldProvider
            
            engine = get_condition_engine()
            engine.register_provider('customer', CustomerFieldProvider())
        except Exception as e:
            # Don't fail app startup if condition engine not available
            import logging
            logging.getLogger(__name__).warning(f"Failed to register CustomerFieldProvider: {e}")

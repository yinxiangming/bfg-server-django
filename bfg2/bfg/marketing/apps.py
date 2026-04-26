# -*- coding: utf-8 -*-
from django.apps import AppConfig


class MarketingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.marketing'
    verbose_name = 'BFG Marketing'
    
    def ready(self):
        """Import signals when app is ready."""
        try:
            import bfg.marketing.signals  # noqa
        except ImportError:
            pass

        try:
            from bfg.marketing.agent_capabilities import register_capabilities
            register_capabilities()
        except ImportError:
            pass

        try:
            from bfg.marketing.roles import register as register_roles
            register_roles()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to register marketing roles")

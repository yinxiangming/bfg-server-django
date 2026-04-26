# -*- coding: utf-8 -*-
from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.support'
    verbose_name = 'BFG Support & Help Desk'
    
    def ready(self):
        """Import signals and register agent capabilities when app is ready."""
        try:
            import bfg.support.signals  # noqa
        except ImportError:
            pass
        try:
            from bfg.support.agent_capabilities import register_capabilities
            register_capabilities()
        except ImportError:
            pass

        try:
            from bfg.support.roles import register as register_roles
            register_roles()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to register support roles")

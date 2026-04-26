# -*- coding: utf-8 -*-
from django.apps import AppConfig


class DeliveryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.delivery'
    verbose_name = 'BFG Delivery & Logistics'
    
    def ready(self):
        """Import signals and register agent capabilities when app is ready."""
        try:
            import bfg.delivery.signals  # noqa
        except ImportError:
            pass
        try:
            from bfg.delivery.agent_capabilities import register_capabilities
            register_capabilities()
        except ImportError:
            pass

        try:
            from bfg.delivery.roles import register as register_roles
            register_roles()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to register delivery roles")

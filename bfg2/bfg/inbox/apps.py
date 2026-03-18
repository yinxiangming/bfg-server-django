# -*- coding: utf-8 -*-
from django.apps import AppConfig


class InboxConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.inbox'
    verbose_name = 'BFG Inbox & Messages'
    
    def ready(self):
        """Import signals when app is ready."""
        try:
            import bfg.inbox.signals  # noqa
        except ImportError:
            pass

        try:
            from bfg.inbox.agent_capabilities import register_capabilities
            register_capabilities()
        except ImportError:
            pass

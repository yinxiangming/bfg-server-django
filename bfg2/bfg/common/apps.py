# -*- coding: utf-8 -*-
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bfg.common'
    verbose_name = 'BFG Common'
    
    def ready(self):
        """Import signals when app is ready."""
        # Python 3.12's mimetypes table knows .avif and .heic but not .webp, and the
        # slim images we deploy on carry no /etc/mime.types to fill the gap. Storage
        # backends guess an object's Content-Type from this table, so every .webp
        # upload lands in S3 as application/octet-stream while .png and .jpg are typed
        # correctly. An <img> renders it anyway by sniffing, which is what makes this
        # easy to miss; opening the URL directly downloads the file instead.
        import mimetypes
        mimetypes.add_type('image/webp', '.webp')

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

        try:
            from bfg.common.agent_capabilities import register_capabilities
            register_capabilities()
        except ImportError:
            pass

        # Register foundational system roles + permission catalog.
        try:
            from bfg.common.roles import register as register_roles
            register_roles()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to register common roles")

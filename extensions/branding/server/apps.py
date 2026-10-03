# -*- coding: utf-8 -*-
from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class BrandPortalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.brand_portal'
    label = 'brand_portal'
    verbose_name = _('Brand Portal')

    def ready(self):
        # The platform console manages a target workspace and therefore must not
        # be bound to the workspace carried by the administrator's JWT.
        console_prefix = '/api/v1/brand_portal/v1/console/'
        extra_public_paths = getattr(settings, 'BFG_EXTRA_PUBLIC_PATHS', ()) or ()
        if isinstance(extra_public_paths, str):
            extra_public_paths = (extra_public_paths,)
        if console_prefix not in extra_public_paths:
            settings.BFG_EXTRA_PUBLIC_PATHS = (*extra_public_paths, console_prefix)

        from apps.brand_portal import signals  # noqa: F401

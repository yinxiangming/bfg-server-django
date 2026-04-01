"""
ASGI config for freight management system.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

from django.core.asgi import get_asgi_application

from config.django_settings_env import setdefault_django_settings_module

setdefault_django_settings_module()

application = get_asgi_application()

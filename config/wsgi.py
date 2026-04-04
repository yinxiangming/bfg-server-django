"""
WSGI config for freight management system.

It exposes the WSGI callable as a module-level variable named ``application``.
"""
from django.core.wsgi import get_wsgi_application

from config.django_settings_env import setdefault_django_settings_module

setdefault_django_settings_module()

application = get_wsgi_application()

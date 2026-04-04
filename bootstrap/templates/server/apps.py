# -*- coding: utf-8 -*-
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class __APP_CONFIG_CLASS__(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = '__APP_MODULE__'
    verbose_name = _('__APP_TITLE__')

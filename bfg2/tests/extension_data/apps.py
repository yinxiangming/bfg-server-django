# -*- coding: utf-8 -*-
"""Test-only app standing in for the tables an extension owns."""

from django.apps import AppConfig


class ExtensionDataTestsConfig(AppConfig):
    name = 'tests.extension_data'
    label = 'extension_data_tests'
    verbose_name = 'Extension Data Tests'
    default_auto_field = 'django.db.models.BigAutoField'

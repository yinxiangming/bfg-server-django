# -*- coding: utf-8 -*-
"""Test-only Django app providing a model that exercises TenantScopedModel."""

from django.apps import AppConfig


class TenantIsolationTestsConfig(AppConfig):
    name = "tests.tenant_isolation"
    label = "tenant_isolation_tests"
    verbose_name = "Tenant Isolation Tests"
    default_auto_field = "django.db.models.BigAutoField"

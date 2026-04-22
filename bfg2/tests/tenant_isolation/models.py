# -*- coding: utf-8 -*-
"""Synthetic models used only by the tenant isolation test suite.

These models exist solely so that the abstract :class:`TenantScopedModel`
contract can be exercised end-to-end (real Django queryset, real DB
table, real workspace FK) without entangling the tests in any of the
production models the broader Phase-0 plan migrates in later PRs.
"""

from django.db import models

from bfg.common.managers import TenantScopedModel


class TenantWidget(TenantScopedModel):
    """Minimal business-shaped record scoped to a workspace."""

    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.CASCADE,
        related_name="+",
    )
    name = models.CharField(max_length=64)

    class Meta:
        app_label = "tenant_isolation_tests"
        # Inherit base_manager_name from TenantScopedModel.Meta so that
        # Django internals (related-manager access, migrations) keep
        # using the unscoped manager.
        base_manager_name = "all_objects"

    def __str__(self):
        return f"TenantWidget(name={self.name!r}, ws={self.workspace_id})"

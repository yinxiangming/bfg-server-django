# -*- coding: utf-8 -*-
"""Behavior contract for ``TenantScopedManager`` / ``TenantScopedModel``.

These tests are the executable spec for Phase-0 PR-01. Adding a model
to :class:`TenantScopedModel` later (PR-05..08) must not be allowed to
break any assertion in this file.
"""

import pytest

from bfg.common.managers import TenantScopedManager, TenantScopedModel
from bfg.common.middleware import (
    get_current_workspace,
    set_current_workspace,
)

from tests.tenant_isolation.models import TenantWidget


pytestmark = pytest.mark.django_db


class TestManagerInstallation:
    """The base class wires the two managers as documented."""

    def test_objects_is_tenant_scoped(self):
        assert isinstance(TenantWidget.objects, TenantScopedManager)

    def test_all_objects_is_plain_manager(self):
        # Not a TenantScopedManager — must be the vanilla escape hatch.
        from django.db import models

        assert type(TenantWidget.all_objects) is models.Manager

    def test_base_manager_is_unscoped(self):
        """Reverse FK / migrations must see all rows, not the scoped subset."""
        assert TenantWidget._meta.base_manager_name == "all_objects"
        assert TenantWidget._base_manager.__class__.__name__ == "Manager"

    def test_abstract_base_does_not_create_a_table(self):
        # Sanity check that TenantScopedModel itself is abstract.
        assert TenantScopedModel._meta.abstract is True


class TestScopedQueryset:
    """``Model.objects`` must filter to the active workspace."""

    def test_returns_only_current_workspace_rows(self, ws_a, ws_b, widget_a, widget_b):
        set_current_workspace(ws_a)
        rows = list(TenantWidget.objects.all())
        assert rows == [widget_a]

        set_current_workspace(ws_b)
        rows = list(TenantWidget.objects.all())
        assert rows == [widget_b]

    def test_count_respects_scope(self, ws_a, widget_a, widget_b):
        set_current_workspace(ws_a)
        assert TenantWidget.objects.count() == 1

    def test_get_for_other_workspace_raises_does_not_exist(
        self, ws_a, widget_a, widget_b
    ):
        set_current_workspace(ws_a)
        with pytest.raises(TenantWidget.DoesNotExist):
            TenantWidget.objects.get(pk=widget_b.pk)

    def test_filter_chain_keeps_scope(self, ws_a, ws_b, widget_a, widget_b):
        set_current_workspace(ws_a)
        # An explicit .filter() must not silently drop the scope.
        assert list(TenantWidget.objects.filter(name__startswith="A")) == [widget_a]
        assert list(TenantWidget.objects.filter(name__startswith="B")) == []


class TestFailClosed:
    """Without a workspace context, callers see nothing — never everything."""

    def test_no_workspace_returns_empty_queryset(self, widget_a, widget_b):
        set_current_workspace(None)
        assert TenantWidget.objects.count() == 0
        assert list(TenantWidget.objects.all()) == []

    def test_no_workspace_get_raises_does_not_exist(self, widget_a):
        set_current_workspace(None)
        with pytest.raises(TenantWidget.DoesNotExist):
            TenantWidget.objects.get(pk=widget_a.pk)


class TestEscapeHatches:
    """Two ways to opt out of scoping — both must surface every row."""

    def test_unscoped_returns_everything(self, widget_a, widget_b):
        set_current_workspace(None)
        rows = list(TenantWidget.objects.unscoped())
        assert {r.pk for r in rows} == {widget_a.pk, widget_b.pk}

    def test_unscoped_works_even_when_workspace_set(
        self, ws_a, widget_a, widget_b
    ):
        # Cross-tenant read must remain available to admin / cron code
        # even when a workspace happens to be bound.
        set_current_workspace(ws_a)
        rows = list(TenantWidget.objects.unscoped())
        assert {r.pk for r in rows} == {widget_a.pk, widget_b.pk}

    def test_all_objects_returns_everything(self, widget_a, widget_b):
        set_current_workspace(None)
        rows = list(TenantWidget.all_objects.all())
        assert {r.pk for r in rows} == {widget_a.pk, widget_b.pk}


class TestThreadLocalIntegration:
    """The manager reads from the same thread-local the middleware writes."""

    def test_manager_sees_middleware_set_value(self, ws_a):
        set_current_workspace(ws_a)
        assert get_current_workspace() == ws_a
        # Use the same accessor pattern the manager uses internally.
        from bfg.common.managers import _get_current_workspace

        assert _get_current_workspace() == ws_a

    def test_clearing_workspace_makes_queryset_empty(self, ws_a, widget_a):
        set_current_workspace(ws_a)
        assert TenantWidget.objects.count() == 1
        set_current_workspace(None)
        assert TenantWidget.objects.count() == 0

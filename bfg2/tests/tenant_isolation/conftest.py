# -*- coding: utf-8 -*-
"""Fixtures shared across the tenant_isolation tests."""

import pytest

from bfg.common.middleware import set_current_workspace
from bfg.common.models import Workspace


@pytest.fixture(autouse=True)
def _reset_workspace_threadlocal():
    """Guarantee no test bleeds workspace state into another."""
    set_current_workspace(None)
    yield
    set_current_workspace(None)


@pytest.fixture
def ws_a(db):
    return Workspace.objects.create(name="Workspace A", slug="ws-a")


@pytest.fixture
def ws_b(db):
    return Workspace.objects.create(name="Workspace B", slug="ws-b")


@pytest.fixture
def widget_a(ws_a):
    from tests.tenant_isolation.models import TenantWidget
    # Use the unscoped manager so creation is independent of the
    # current workspace context — tests want to control that.
    return TenantWidget.all_objects.create(workspace=ws_a, name="A-widget")


@pytest.fixture
def widget_b(ws_b):
    from tests.tenant_isolation.models import TenantWidget
    return TenantWidget.all_objects.create(workspace=ws_b, name="B-widget")

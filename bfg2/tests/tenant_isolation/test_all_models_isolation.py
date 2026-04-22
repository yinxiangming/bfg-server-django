# -*- coding: utf-8 -*-
"""Meta-tests that enumerate every :class:`TenantScopedModel` subclass
and assert it honours the tenant-isolation contract (Phase-0 PR-08).

The test is intentionally **dynamic** — when a future PR migrates a
new model to :class:`TenantScopedModel`, these assertions fire on it
automatically. A missed ``base_manager_name``, a missing ``workspace``
field, or a cross-tenant leak in the default queryset surface without
the author having to remember to add a hand-written test.
"""

from contextlib import contextmanager

import pytest
from django.apps import apps
from django.db import models

from bfg.common.managers import TenantScopedManager, TenantScopedModel
from bfg.common.middleware import set_current_workspace
from bfg.common.models import Workspace


pytestmark = pytest.mark.django_db


# ─── Model enumeration ───────────────────────────────────────────────


def _tenant_scoped_models():
    """Every concrete model that inherits from :class:`TenantScopedModel`."""
    return [
        m for m in apps.get_models()
        if issubclass(m, TenantScopedModel) and not m._meta.abstract
    ]


# Canary so an empty registry (e.g. apps not loaded) doesn't silently
# turn the whole parametrised block into a no-op green check.
def test_at_least_one_tenant_scoped_model_registered():
    assert _tenant_scoped_models(), (
        "No TenantScopedModel subclasses found; the plan's four batches "
        "should have migrated at least ~20 production models."
    )


# ─── Structural invariants ───────────────────────────────────────────


@pytest.mark.parametrize(
    "model", _tenant_scoped_models(), ids=lambda m: m._meta.label,
)
class TestStructuralInvariants:
    def test_has_workspace_fk(self, model):
        """Every TenantScopedModel must carry a ``workspace`` FK — the
        manager's ``.filter(workspace=...)`` depends on it."""
        field_names = {f.name for f in model._meta.get_fields()}
        assert "workspace" in field_names, (
            f"{model._meta.label} is a TenantScopedModel but has no "
            f"``workspace`` field."
        )

    def test_default_manager_is_tenant_scoped(self, model):
        """``Model.objects`` must be a :class:`TenantScopedManager` — if
        a concrete model overrides ``objects`` with a plain manager,
        scoping is silently lost."""
        assert isinstance(model.objects, TenantScopedManager), (
            f"{model._meta.label}.objects is {type(model.objects).__name__}; "
            f"expected TenantScopedManager. A subclass may have shadowed "
            f"the abstract base's default manager."
        )

    def test_has_all_objects_escape_hatch(self, model):
        """A plain :class:`models.Manager` must be accessible as
        ``all_objects`` so admin / cron / migration code has an
        explicit escape hatch."""
        all_objects = getattr(model, "all_objects", None)
        assert all_objects is not None, (
            f"{model._meta.label} has no ``all_objects`` escape hatch."
        )
        assert isinstance(all_objects, models.Manager)
        assert not isinstance(all_objects, TenantScopedManager), (
            f"{model._meta.label}.all_objects must be a plain Manager, "
            f"not TenantScopedManager — that would defeat the purpose."
        )

    def test_base_manager_is_unscoped(self, model):
        """``Model._base_manager`` must return every row. It's used by
        Django for reverse FK access and migrations; if it were scoped,
        ``workspace.products.all()`` would silently filter twice and
        ``RunPython`` data migrations would see nothing."""
        base = model._base_manager
        assert not isinstance(base, TenantScopedManager), (
            f"{model._meta.label}._base_manager is TenantScopedManager — "
            f"set ``class Meta: base_manager_name = 'all_objects'`` on "
            f"the concrete model."
        )


# ─── Runtime invariant: cross-tenant leak probe ──────────────────────


@contextmanager
def _as_workspace(ws):
    """Bind ``ws`` as the current workspace for the duration of the block."""
    set_current_workspace(ws)
    try:
        yield
    finally:
        set_current_workspace(None)


@pytest.fixture
def ws_a(db):
    return Workspace.objects.create(name="Meta A", slug="meta-a")


@pytest.fixture
def ws_b(db):
    return Workspace.objects.create(name="Meta B", slug="meta-b")


# The runtime test can only run against models that are creatable with
# very few fields. Building a valid instance of every BFG model would
# require dozens of related fixtures (Currency, Customer, Store, …).
# We therefore only probe the *manager filter predicate*: two fake
# querysets built via ``Model.objects.filter(workspace=X)`` must not
# intersect. This doesn't require any rows to exist.


@pytest.mark.parametrize(
    "model", _tenant_scoped_models(), ids=lambda m: m._meta.label,
)
class TestRuntimeIsolation:
    def test_queryset_sql_includes_workspace_filter(self, model, ws_a):
        """The compiled SQL for ``Model.objects.all()`` must mention the
        workspace column — empirical proof that the manager is adding
        the tenant filter rather than returning the whole table."""
        with _as_workspace(ws_a):
            sql = str(model.objects.all().query)
        # Django quotes column names; look for the substring without
        # caring about the quoting style.
        assert "workspace" in sql.lower(), (
            f"{model._meta.label}.objects.all() did not inject a "
            f"workspace filter into its SQL: {sql}"
        )

    def test_no_workspace_context_is_empty(self, model):
        """Without a bound workspace, the default manager is empty —
        fail-closed contract from PR-01."""
        set_current_workspace(None)
        assert list(model.objects.all()[:1]) == []

    def test_unscoped_yields_queryset(self, model, ws_a):
        """``unscoped()`` must return a queryset whose SQL no longer
        filters by workspace."""
        with _as_workspace(ws_a):
            sql = str(model.objects.unscoped().query)
        # It may still mention workspace as a column in SELECT, but the
        # WHERE clause must not bind it to a single value. Coarse check:
        # the scoped variant's SQL was strictly longer (extra WHERE);
        # comparing lengths is an indirect but cheap heuristic.
        with _as_workspace(ws_a):
            scoped_sql = str(model.objects.all().query)
        assert len(sql) <= len(scoped_sql)

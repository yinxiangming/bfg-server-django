# -*- coding: utf-8 -*-
"""Global pytest fixtures (Phase-0 PR-08)."""

import pytest


@pytest.fixture(autouse=True)
def _clean_workspace_threadlocal():
    """Reset the request-scoped workspace between every test.

    ``BaseService.__init__`` (Phase-0 PR-08) sets the thread-local
    workspace so services work outside a request context. That makes
    test ordering matter: a service instantiated with a fake
    ``SimpleNamespace`` workspace would leak into the next test's
    ``TenantScopedManager`` queries. Clearing here before *and* after
    each test eliminates the ordering coupling.
    """
    from bfg.common.middleware import set_current_workspace

    set_current_workspace(None)
    yield
    set_current_workspace(None)

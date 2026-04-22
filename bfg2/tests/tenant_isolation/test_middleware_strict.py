# -*- coding: utf-8 -*-
"""Strict-mode WorkspaceMiddleware contract (Phase-0 PR-04+PR-09).

The legacy fallback ``_get_first_active_workspace`` is gone. Every
request now lands on one of four paths:

* PUBLIC_PATHS → ``request.workspace = None``, let through.
* Header/domain resolves a workspace → bind, hydrate, let through.
* Delegating auth header (``X-API-Key``) present → let through; the
  view-layer authentication will populate workspace.
* Nothing of the above → ``400 workspace_required``.
"""

import pytest
from django.test import Client

from bfg.common.middleware import (
    PUBLIC_PATHS,
    WORKSPACE_DELEGATING_HEADERS,
    MISSING_WORKSPACE_RESPONSE,
    _thread_locals,
    get_current_workspace,
)
from bfg.common.models import Workspace


pytestmark = pytest.mark.django_db


@pytest.fixture
def ws(db):
    return Workspace.objects.create(name="Strict", slug="strict", is_active=True)


@pytest.fixture(autouse=True)
def _clean_threadlocal():
    if hasattr(_thread_locals, "workspace"):
        del _thread_locals.workspace
    yield
    if hasattr(_thread_locals, "workspace"):
        del _thread_locals.workspace


# ─── Fallback is gone ────────────────────────────────────────────────


class TestFallbackRemoved:
    def test_request_without_workspace_returns_400(self, ws):
        """Even with an active workspace in the DB, strict mode refuses
        an unidentified request — this is the whole PR-09 contract."""
        response = Client().get("/api/v1/__strict_probe__/")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "workspace_required"
        assert body == MISSING_WORKSPACE_RESPONSE

    def test_no_get_first_active_workspace_symbol(self):
        import bfg.common.middleware as mw

        assert not hasattr(mw, "_get_first_active_workspace"), (
            "Legacy fallback _get_first_active_workspace must be deleted "
            "per Phase-0 PR-09 to prevent cross-tenant default binding."
        )


# ─── PUBLIC_PATHS bypass ─────────────────────────────────────────────


class TestPublicPaths:
    @pytest.mark.parametrize("prefix", PUBLIC_PATHS)
    def test_every_public_prefix_bypasses_workspace_check(self, prefix):
        # Hit a path that starts with the prefix; middleware must not 400.
        probe = f"{prefix.rstrip('/')}/__probe__/"
        response = Client().get(probe)
        # 400 specifically means the strict check rejected it. Anything
        # else (404, 200, 302) means middleware let the request through.
        assert response.status_code != 400, (
            f"Public prefix {prefix!r} was incorrectly rejected by "
            f"strict workspace check."
        )


# ─── Header-based resolution ─────────────────────────────────────────


class TestHeaderResolution:
    def test_valid_workspace_header_is_accepted(self, ws):
        response = Client().get(
            "/api/v1/__strict_probe__/",
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        assert response.status_code != 400

    def test_unknown_workspace_id_still_rejected(self):
        response = Client().get(
            "/api/v1/__strict_probe__/",
            HTTP_X_WORKSPACE_ID="9999999",
        )
        # Unknown ID resolves to None → same as missing header.
        assert response.status_code == 400
        assert response.json()["code"] == "workspace_required"

    def test_inactive_workspace_id_rejected(self, ws):
        ws.is_active = False
        ws.save()
        response = Client().get(
            "/api/v1/__strict_probe__/",
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        assert response.status_code == 400

    def test_non_numeric_workspace_id_rejected(self):
        response = Client().get(
            "/api/v1/__strict_probe__/",
            HTTP_X_WORKSPACE_ID="not-a-number",
        )
        assert response.status_code == 400


# ─── API-key delegation ──────────────────────────────────────────────


class TestApiKeyDelegation:
    def test_api_key_header_bypasses_400(self):
        # View-layer auth will either resolve the key to a workspace or
        # reject with 401/403; the middleware just needs to let it
        # through without the 400 short-circuit.
        response = Client().get(
            "/api/v1/__strict_probe__/",
            HTTP_X_API_KEY="bogus-key-for-middleware-test",
        )
        assert response.status_code != 400

    def test_delegation_header_set_contains_x_api_key(self):
        # Guard the header list doesn't accidentally grow/shrink.
        assert "X-API-Key" in WORKSPACE_DELEGATING_HEADERS


# ─── Thread-local cleanup ────────────────────────────────────────────


class TestThreadLocalCleanup:
    def test_workspace_cleared_after_successful_request(self, ws):
        Client().get(
            "/api/v1/__strict_probe__/",
            HTTP_X_WORKSPACE_ID=str(ws.id),
        )
        # No way to observe mid-request state from here, but the post-
        # condition is testable: after the response comes back, thread-
        # local must be empty so the next request (which may run on the
        # same OS thread) doesn't inherit.
        assert get_current_workspace() is None

    def test_workspace_cleared_after_400(self):
        Client().get("/api/v1/__strict_probe__/")
        assert get_current_workspace() is None

    def test_workspace_cleared_after_public_path(self):
        Client().get("/api/v1/auth/__probe__/")
        assert get_current_workspace() is None

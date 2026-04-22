# -*- coding: utf-8 -*-
"""Behaviour contract for SecurityHeadersMiddleware (Phase-0 PR-02).

Two layers of tests:

* **Unit** — build the middleware with controlled settings and verify
  its header output. No Django client, no URL routing.
* **Integration** — fire a request through the whole middleware chain
  (SecurityHeadersMiddleware is registered in tests/settings.py) and
  verify the response carries every header we promise.
"""

from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.test import Client

from bfg.common.security_headers import (
    SecurityHeadersMiddleware,
    STATIC_HEADERS,
    build_csp,
)


# ─── Unit: build_csp ──────────────────────────────────────────────────


class TestBuildCsp:
    def test_default_api_origins_collapses_to_self(self):
        csp = build_csp(None)
        # connect-src must include 'self' even when no extra API origins
        # are configured — we never want a missing env var to widen CSP.
        assert "connect-src 'self' 'self' https://api.stripe.com" in csp

    def test_extra_api_origins_are_joined(self):
        csp = build_csp(["https://api.example.com", "https://api-b.example.com"])
        assert "https://api.example.com https://api-b.example.com" in csp
        assert "connect-src 'self' https://api.example.com https://api-b.example.com" in csp

    def test_all_required_directives_present(self):
        csp = build_csp(None)
        required = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://js.stripe.com",
            "connect-src",
            "img-src 'self' data: https:",
            "style-src 'self' 'unsafe-inline'",
            "frame-src https://js.stripe.com https://hooks.stripe.com",
            "frame-ancestors 'none'",
        ]
        for directive in required:
            assert directive in csp, f"missing directive: {directive}"

    def test_frame_ancestors_none_blocks_iframe_embedding(self):
        # This is the defence against clickjacking of the backend
        # (e.g. admin pages) from third-party frames.
        assert "frame-ancestors 'none';" in build_csp(None)


# ─── Unit: middleware header wiring ───────────────────────────────────


def _make_middleware(*, env):
    """Build the middleware as if ``settings.ENV`` were ``env``."""

    def _get_response(request):
        return HttpResponse("ok")

    with patch("bfg.common.security_headers.settings") as mock_settings:
        mock_settings.ENV = env
        mock_settings.CSP_API_ORIGINS = ["'self'"]
        # getattr() calls in the middleware resolve to these mocked attrs.
        mock_settings.configure_mock(ENV=env, CSP_API_ORIGINS=["'self'"])
        return SecurityHeadersMiddleware(_get_response)


class TestHeaderOutput:
    def test_all_static_headers_applied(self, rf):
        mw = _make_middleware(env="test")
        response = mw(rf.get("/"))
        for name, value in STATIC_HEADERS.items():
            assert response[name] == value, f"header {name} wrong"

    def test_permissions_policy_disables_sensors(self, rf):
        mw = _make_middleware(env="test")
        response = mw(rf.get("/"))
        policy = response["Permissions-Policy"]
        for capability in (
            "camera=()", "geolocation=()", "microphone=()",
            "payment=()", "usb=()",
        ):
            assert capability in policy

    def test_x_frame_options_is_deny(self, rf):
        mw = _make_middleware(env="test")
        response = mw(rf.get("/"))
        assert response["X-Frame-Options"] == "DENY"

    def test_csp_is_report_only_in_non_prod(self, rf):
        mw = _make_middleware(env="dev")
        response = mw(rf.get("/"))
        assert "Content-Security-Policy-Report-Only" in response
        assert "Content-Security-Policy" not in response

    def test_csp_is_enforced_in_prod(self, rf):
        mw = _make_middleware(env="prod")
        response = mw(rf.get("/"))
        assert "Content-Security-Policy" in response
        assert "Content-Security-Policy-Report-Only" not in response

    def test_csp_value_includes_stripe(self, rf):
        mw = _make_middleware(env="prod")
        response = mw(rf.get("/"))
        value = response["Content-Security-Policy"]
        assert "https://js.stripe.com" in value
        assert "https://hooks.stripe.com" in value

    def test_upstream_header_not_overwritten(self, rf):
        """``setdefault`` — an upstream view may opt in to something stricter."""

        def _get_response(request):
            r = HttpResponse("ok")
            r["X-Frame-Options"] = "SAMEORIGIN"
            return r

        with patch("bfg.common.security_headers.settings") as mock_settings:
            mock_settings.configure_mock(ENV="test", CSP_API_ORIGINS=["'self'"])
            mw = SecurityHeadersMiddleware(_get_response)
        response = mw(rf.get("/"))
        # The upstream value survives.
        assert response["X-Frame-Options"] == "SAMEORIGIN"


# ─── Integration: full middleware chain ───────────────────────────────


@pytest.mark.django_db
class TestIntegration:
    """SecurityHeadersMiddleware is registered in tests/settings.py —
    any response through the Django test client must carry the headers."""

    def test_headers_attached_to_404_response(self):
        client = Client()
        # Hit a URL that almost certainly doesn't match — middleware still
        # runs on error responses, which is exactly the invariant we want.
        response = client.get("/__definitely_not_a_real_url__/")
        assert response.status_code == 404
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in response

    def test_report_only_csp_in_test_env(self):
        client = Client()
        response = client.get("/__definitely_not_a_real_url__/")
        # tests/settings.py sets ENV='test' so we expect Report-Only.
        assert "Content-Security-Policy-Report-Only" in response
        assert "default-src 'self'" in response["Content-Security-Policy-Report-Only"]

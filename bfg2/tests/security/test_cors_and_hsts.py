# -*- coding: utf-8 -*-
"""CORS whitelist + HSTS behaviour for Phase-0 PR-02.

These exercises lean on django-cors-headers and Django's own
``SecurityMiddleware`` respectively — we're not re-implementing either,
just verifying our settings.py plumbing reaches them.
"""

from django.test import Client


ALLOWED_ORIGIN = "https://app.example.com"
DISALLOWED_ORIGIN = "https://evil.example.com"


# ─── CORS ────────────────────────────────────────────────────────────


class TestCorsWhitelist:
    def test_whitelisted_origin_gets_allow_origin_header(self, settings):
        settings.CORS_ALLOW_ALL_ORIGINS = False
        settings.CORS_ALLOWED_ORIGINS = [ALLOWED_ORIGIN]
        response = Client().options(
            "/__cors_probe__/",
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        assert response.get("Access-Control-Allow-Origin") == ALLOWED_ORIGIN

    def test_unlisted_origin_is_rejected(self, settings):
        settings.CORS_ALLOW_ALL_ORIGINS = False
        settings.CORS_ALLOWED_ORIGINS = [ALLOWED_ORIGIN]
        response = Client().options(
            "/__cors_probe__/",
            HTTP_ORIGIN=DISALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        # Browser short-circuits when header missing — exactly what we
        # want for a cross-origin caller that isn't on the allow list.
        assert "Access-Control-Allow-Origin" not in response


# ─── HSTS — proxied by Django's own SecurityMiddleware ────────────────


class TestHstsHeader:
    def test_hsts_header_set_on_secure_request(self, settings):
        settings.SECURE_HSTS_SECONDS = 31536000
        settings.SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        settings.SECURE_HSTS_PRELOAD = True
        response = Client().get("/__hsts_probe__/", secure=True)
        sts = response.get("Strict-Transport-Security", "")
        assert "max-age=31536000" in sts
        assert "includeSubDomains" in sts
        assert "preload" in sts

    def test_no_hsts_on_plain_http_request(self, settings):
        # SecurityMiddleware only emits HSTS on an already-HTTPS request
        # (anything else would be a no-op that tricks auditors).
        settings.SECURE_HSTS_SECONDS = 31536000
        response = Client().get("/__hsts_probe__/", secure=False)
        assert "Strict-Transport-Security" not in response


# ─── Env helpers sanity check ────────────────────────────────────────


class TestEnvHelpers:
    def test_env_list_splits_comma_separated(self, monkeypatch):
        monkeypatch.setenv("BFG_PR02_TEST_LIST", "a, b ,c,,d")
        from config.settings import _env_list  # noqa: PLC0415

        assert _env_list("BFG_PR02_TEST_LIST") == ["a", "b", "c", "d"]

    def test_env_list_empty_returns_default(self, monkeypatch):
        monkeypatch.delenv("BFG_PR02_TEST_LIST_MISSING", raising=False)
        from config.settings import _env_list  # noqa: PLC0415

        assert _env_list("BFG_PR02_TEST_LIST_MISSING", default=["x"]) == ["x"]

    def test_env_bool_truthy_values(self, monkeypatch):
        from config.settings import _env_bool  # noqa: PLC0415

        for truthy in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("BFG_PR02_BOOL", truthy)
            assert _env_bool("BFG_PR02_BOOL", default=False) is True

    def test_env_bool_unset_returns_default(self, monkeypatch):
        from config.settings import _env_bool  # noqa: PLC0415

        monkeypatch.delenv("BFG_PR02_BOOL_UNSET", raising=False)
        assert _env_bool("BFG_PR02_BOOL_UNSET", default=True) is True
        assert _env_bool("BFG_PR02_BOOL_UNSET", default=False) is False

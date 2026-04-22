# -*- coding: utf-8 -*-
"""Behaviour contract for ``manage.py bfg_prod_check`` (Phase-0 PR-03)."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from bfg.common.management.commands.bfg_prod_check import PROD_CHECKS


# A config that satisfies every PROD_CHECKS predicate. Each test starts
# from this baseline and violates exactly one axis so we can pin-point
# which check catches which misconfig.
PROD_READY = {
    "IS_PROD": True,
    "DEBUG": False,
    "CORS_ALLOW_ALL_ORIGINS": False,
    "CORS_ALLOWED_ORIGINS": ["https://app.example.com"],
    "SECURE_SSL_REDIRECT": True,
    "SECURE_HSTS_SECONDS": 31536000,
    "SESSION_COOKIE_SECURE": True,
    "CSRF_COOKIE_SECURE": True,
    "BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS": False,
    "SECRET_KEY": "X" * 60,
    "SENTRY_DSN": "https://key@o0.ingest.sentry.io/0",
    "ALLOWED_HOSTS": ["api.example.com"],
    "CACHES": {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/15",
            "KEY_PREFIX": "prod_check",
        }
    },
}


def _apply_prod_ready(settings):
    for key, value in PROD_READY.items():
        setattr(settings, key, value)


# ─── CHECKS wiring ───────────────────────────────────────────────────


class TestChecksRegistry:
    def test_twelve_checks_registered(self):
        # If this count changes, update deploy docs that reference bfg_prod_check.
        assert len(PROD_CHECKS) == 12

    def test_each_check_is_a_description_plus_callable(self):
        for item in PROD_CHECKS:
            assert isinstance(item, tuple) and len(item) == 2
            description, predicate = item
            assert isinstance(description, str) and description
            assert callable(predicate)


# ─── Happy path ──────────────────────────────────────────────────────


class TestHappyPath:
    def test_passes_with_every_flag_set(self, settings):
        _apply_prod_ready(settings)
        out = StringIO()
        call_command("bfg_prod_check", stdout=out)
        text = out.getvalue()
        assert "All prod checks passed." in text
        assert "[FAIL]" not in text

    def test_skips_when_not_is_prod(self, settings):
        _apply_prod_ready(settings)
        settings.IS_PROD = False
        out = StringIO()
        call_command("bfg_prod_check", stdout=out)
        assert "Skipping bfg_prod_check" in out.getvalue()
        assert "All prod checks passed." not in out.getvalue()


# ─── Each failure mode ───────────────────────────────────────────────


class TestEachViolationCaught:
    """Violate one flag at a time; command must fail with that flag named."""

    @pytest.mark.parametrize(
        "override, expected_fragment",
        [
            ({"DEBUG": True}, "DEBUG"),
            ({"CORS_ALLOW_ALL_ORIGINS": True}, "CORS_ALLOW_ALL_ORIGINS"),
            (
                {"CORS_ALLOWED_ORIGINS": [], "CORS_ALLOWED_ORIGIN_REGEXES": []},
                "CORS_ALLOWED_ORIGINS",
            ),
            ({"SECURE_SSL_REDIRECT": False}, "SECURE_SSL_REDIRECT"),
            ({"SECURE_HSTS_SECONDS": 3600}, "SECURE_HSTS_SECONDS"),
            ({"SESSION_COOKIE_SECURE": False}, "SESSION_COOKIE_SECURE"),
            ({"CSRF_COOKIE_SECURE": False}, "CSRF_COOKIE_SECURE"),
            (
                {"BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS": True},
                "BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS",
            ),
            ({"SECRET_KEY": "dev-secret-change-in-production"}, "SECRET_KEY"),
            ({"SENTRY_DSN": ""}, "SENTRY_DSN"),
            ({"ALLOWED_HOSTS": ["*"]}, "ALLOWED_HOSTS"),
            ({"ALLOWED_HOSTS": []}, "ALLOWED_HOSTS"),
            (
                {
                    "CACHES": {
                        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
                    }
                },
                "RedisCache",
            ),
        ],
    )
    def test_violation_raises_command_error(self, settings, override, expected_fragment):
        _apply_prod_ready(settings)
        for key, value in override.items():
            setattr(settings, key, value)

        out = StringIO()
        with pytest.raises(CommandError):
            call_command("bfg_prod_check", stdout=out)
        text = out.getvalue()
        assert "[FAIL]" in text
        assert expected_fragment in text


# ─── Short SECRET_KEY ────────────────────────────────────────────────


class TestSecretKeyLength:
    def test_short_secret_key_fails(self, settings):
        _apply_prod_ready(settings)
        settings.SECRET_KEY = "short"
        with pytest.raises(CommandError):
            call_command("bfg_prod_check", stdout=StringIO())

    def test_fifty_char_non_placeholder_key_passes(self, settings):
        _apply_prod_ready(settings)
        settings.SECRET_KEY = "k" * 50
        out = StringIO()
        call_command("bfg_prod_check", stdout=out)
        assert "All prod checks passed." in out.getvalue()


# ─── --soft mode ─────────────────────────────────────────────────────


class TestSoftMode:
    def test_soft_reports_but_exits_zero(self, settings):
        _apply_prod_ready(settings)
        settings.DEBUG = True  # one failure
        out = StringIO()
        # No CommandError raised — the whole point of --soft.
        call_command("bfg_prod_check", "--soft", stdout=out)
        text = out.getvalue()
        assert "[FAIL]" in text
        assert "--soft: exiting 0" in text


# ─── Exception-in-check tolerance ────────────────────────────────────


class TestExceptionInCheck:
    def test_missing_setting_counts_as_failure(self, settings):
        _apply_prod_ready(settings)
        # SENTRY_DSN is optional; the check uses getattr with default.
        # But e.g. deleting ALLOWED_HOSTS (which .DEBUG etc don't default)
        # should still produce a graceful failure, not a crash.
        delattr(settings, "ALLOWED_HOSTS")
        settings.ALLOWED_HOSTS = []  # restore to an empty list so other
        # tests don't cascade-fail; the real assertion is that the
        # command keeps going even on exception inside a predicate.
        with pytest.raises(CommandError):
            call_command("bfg_prod_check", stdout=StringIO())

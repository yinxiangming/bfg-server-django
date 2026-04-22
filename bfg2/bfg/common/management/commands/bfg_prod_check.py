# -*- coding: utf-8 -*-
"""Production configuration self-check (Phase-0 PR-03).

Intended to run in the container entrypoint *before* Gunicorn binds
the port, so a misconfigured deploy dies fast instead of serving
requests with a half-open security posture.

Each check is a ``(description, predicate)`` pair. Predicates take
``django.conf.settings`` and return a truthy value when the config is
acceptable. A single failed predicate is enough to exit non-zero —
there is no severity gradient on purpose.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# Module-level so tests can import and assert on the exact CHECKS list
# without instantiating the Command class.
PROD_CHECKS = (
    (
        "DEBUG must be False in prod",
        lambda s: s.DEBUG is False,
    ),
    (
        "CORS_ALLOW_ALL_ORIGINS must be False",
        lambda s: s.CORS_ALLOW_ALL_ORIGINS is False,
    ),
    (
        "CORS_ALLOWED_ORIGINS / CORS_ALLOWED_ORIGIN_REGEXES must be non-empty",
        lambda s: bool(
            getattr(s, "CORS_ALLOWED_ORIGINS", None)
            or getattr(s, "CORS_ALLOWED_ORIGIN_REGEXES", None)
        ),
    ),
    (
        "SECURE_SSL_REDIRECT must be True",
        lambda s: s.SECURE_SSL_REDIRECT is True,
    ),
    (
        "SECURE_HSTS_SECONDS must be >= 31536000 (1 year)",
        lambda s: getattr(s, "SECURE_HSTS_SECONDS", 0) >= 31536000,
    ),
    (
        "SESSION_COOKIE_SECURE must be True",
        lambda s: getattr(s, "SESSION_COOKIE_SECURE", False) is True,
    ),
    (
        "CSRF_COOKIE_SECURE must be True",
        lambda s: getattr(s, "CSRF_COOKIE_SECURE", False) is True,
    ),
    (
        "BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS must be False",
        lambda s: getattr(s, "BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS", True) is False,
    ),
    (
        "SECRET_KEY must be >= 50 chars and not the default dev placeholder",
        lambda s: (
            len(s.SECRET_KEY) >= 50
            and "dev-secret-change-in-production" not in s.SECRET_KEY
            and "test-insecure" not in s.SECRET_KEY
        ),
    ),
    (
        "ALLOWED_HOSTS must be explicit (no wildcard) and non-empty",
        lambda s: bool(s.ALLOWED_HOSTS) and "*" not in s.ALLOWED_HOSTS,
    ),
    (
        "CACHES['default'] must use django.core.cache.backends.redis.RedisCache "
        "(set DJANGO_CACHE_URL in prod so all workers share cache)",
        lambda s: getattr(s, "CACHES", {})
        .get("default", {})
        .get("BACKEND", "")
        == "django.core.cache.backends.redis.RedisCache",
    ),
)


class Command(BaseCommand):
    help = (
        "Fail-fast production configuration check. "
        "Intended to run from the container entrypoint before the web server starts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--soft",
            action="store_true",
            help=(
                "Report failures but exit 0 — useful during gradual rollouts "
                "where a failure should page on-call without killing the deploy."
            ),
        )

    def handle(self, *args, **opts):
        # Only enforce when the deployment is production; UAT/staging often
        # relaxes DEBUG/Sentry/CORS and must not block `release` on Dokku.
        if not getattr(settings, "IS_PROD", False):
            self.stdout.write(
                "Skipping bfg_prod_check: IS_PROD is False (non-production)."
            )
            return

        failed = []
        passed = []

        for description, predicate in PROD_CHECKS:
            ok, detail = self._run_check(predicate, description)
            line = f"  [{'PASS' if ok else 'FAIL'}] {description}"
            if not ok and detail:
                line += f"  ({detail})"
            self.stdout.write(line)
            (passed if ok else failed).append(description)

        self.stdout.write("")
        self.stdout.write(
            f"Summary: {len(passed)} passed, {len(failed)} failed"
        )

        if not failed:
            self.stdout.write(self.style.SUCCESS("All prod checks passed."))
            return

        msg = f"Production config check failed: {len(failed)} issue(s)"
        if opts.get("soft"):
            self.stdout.write(self.style.WARNING(f"{msg} (--soft: exiting 0)"))
            return
        raise CommandError(msg)

    @staticmethod
    def _run_check(predicate, description):
        """Run a predicate, treating exceptions as failure.

        Returns ``(ok, detail_message_or_empty)``.
        """
        try:
            return bool(predicate(settings)), ""
        except Exception as exc:  # noqa: BLE001 — the check catches *everything*
            return False, f"exception: {exc.__class__.__name__}: {exc}"

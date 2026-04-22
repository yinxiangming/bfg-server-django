# -*- coding: utf-8 -*-
"""Security response headers for BFG2.

Django's own :class:`django.middleware.security.SecurityMiddleware`
already handles HSTS, SSL redirect, and the ``X-Content-Type-Options``
header when the matching settings flags are turned on. This middleware
layers on the *other* defence-in-depth headers Django does not ship
with defaults for:

* ``X-Frame-Options`` — belt-and-braces on top of
  :class:`django.middleware.clickjacking.XFrameOptionsMiddleware`.
* ``Referrer-Policy`` — opt in to the modern default.
* ``Permissions-Policy`` — disable every sensor/capability the backend
  never needs to advertise to a browser.
* ``Content-Security-Policy`` (enforce in prod,
  ``Content-Security-Policy-Report-Only`` elsewhere) — default-deny
  with explicit allow-lists for the third parties the app integrates
  with (Stripe, Sentry).

Every header is set via ``response.setdefault`` so an upstream view or
middleware that has already opted in to a stricter value keeps it.
"""

from django.conf import settings


STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), "
        "gyroscope=(), magnetometer=(), microphone=(), "
        "payment=(), usb=()"
    ),
}


def build_csp(api_origins=None):
    """Return the Content-Security-Policy header value.

    ``api_origins`` — iterable of host patterns that the browser is
    allowed to XHR/``fetch`` into (``connect-src``). Defaults to
    ``('self',)`` so a mis-configured env never widens the policy.
    """
    api = " ".join(api_origins or ["'self'"])
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
        f"connect-src 'self' {api} https://api.stripe.com https://*.sentry.io; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "frame-src https://js.stripe.com https://hooks.stripe.com; "
        "frame-ancestors 'none';"
    )


class SecurityHeadersMiddleware:
    """Attach the static security headers + CSP to every response."""

    def __init__(self, get_response):
        self.get_response = get_response
        # CSP is computed once at process start — directives do not
        # change per request and re-computing would be wasteful.
        self._csp_value = build_csp(
            getattr(settings, "CSP_API_ORIGINS", None)
        )
        self._csp_header = self._pick_csp_header_name()

    @staticmethod
    def _pick_csp_header_name():
        """Enforce in prod, observe elsewhere.

        Plan §2.4: non-prod should ship ``Content-Security-Policy-Report-Only``
        so violations surface in the browser console without breaking
        pages while the policy is being tuned.
        """
        env = getattr(settings, "ENV", "dev")
        if env == "prod":
            return "Content-Security-Policy"
        return "Content-Security-Policy-Report-Only"

    def __call__(self, request):
        response = self.get_response(request)
        for name, value in STATIC_HEADERS.items():
            response.setdefault(name, value)
        response.setdefault(self._csp_header, self._csp_value)
        return response

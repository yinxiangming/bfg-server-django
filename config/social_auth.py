# -*- coding: utf-8 -*-
"""
Social login (Google, Apple, Facebook) with JWT bridge.

Stores redirect/host in session on login start; on OAuth callback, generates JWT
and redirects to frontend with token in URL fragment (no session cookie).
"""
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework_simplejwt.tokens import RefreshToken

from allauth.socialaccount.providers.google.views import (
    oauth2_login as google_oauth2_login,
    oauth2_callback as google_oauth2_callback,
)
from allauth.socialaccount.providers.facebook.views import (
    oauth2_login as facebook_oauth2_login,
    oauth2_callback as facebook_oauth2_callback,
)


# Session keys for frontend redirect and workspace host (from login view)
SOCIAL_REDIRECT_KEY = 'social_login_redirect'
SOCIAL_HOST_KEY = 'social_login_host'


def _allowed_frontend_origins():
    """Frontend origins permitted as social-login callback hosts.

    Pulled from CORS_ALLOWED_ORIGINS so the existing CORS allowlist is the
    single source of truth — adding a new frontend means updating one list.
    Returned as a {host_lower: origin} map for case-insensitive lookup.
    """
    origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', None) or []
    result = {}
    for origin in origins:
        origin = (origin or '').strip().rstrip('/')
        if not origin or '://' not in origin:
            continue
        host = origin.split('://', 1)[1].split('/', 1)[0]
        result[host.lower()] = origin
    return result


def _get_frontend_base_url(request, requested_host=None):
    """Frontend base URL (no trailing slash).

    If `requested_host` (captured at login start from the originating frontend)
    matches an allowed CORS origin, that origin wins — so users coming from
    e.g. idlevo.com get redirected back to idlevo.com, not the FRONTEND_URL
    default. Unknown hosts fall through to FRONTEND_URL, then a localhost dev
    fallback. The CORS check is what prevents an attacker from supplying an
    arbitrary host to harvest tokens.
    """
    if requested_host:
        host = requested_host.strip().split(':', 1)[0].lower()
        allowed = _allowed_frontend_origins()
        match = allowed.get(host)
        if match:
            return match
    base = (getattr(settings, 'FRONTEND_URL', '') or '').strip()
    if base:
        return base.rstrip('/')
    # Final fallback (local dev without FRONTEND_URL set): same host, port 3000.
    scheme = request.scheme
    host = request.get_host().split(':')[0]
    return f'{scheme}://{host}:3000'


def _build_callback_url_with_fragment(request, access, refresh, redirect_path, requested_host=None):
    """Build frontend /auth/callback URL with access, refresh, redirect in fragment."""
    base = _get_frontend_base_url(request, requested_host=requested_host)
    fragment = urlencode({
        'access': access,
        'refresh': refresh,
        'redirect': redirect_path or '/account',
    })
    return f'{base}/auth/callback#{fragment}'


@require_http_methods(['GET', 'POST'])
def social_login_view(request, provider):
    """
    Start social login: store redirect and host in session, then redirect to provider.
    GET from frontend; POST may be used by allauth's intermediate form.
    """
    data = request.GET if request.method == 'GET' else request.POST
    request.session[SOCIAL_REDIRECT_KEY] = data.get('redirect', '/account')
    request.session[SOCIAL_HOST_KEY] = data.get('host', '')
    request.session.modified = True

    if provider == 'google':
        return google_oauth2_login(request)
    if provider == 'facebook':
        return facebook_oauth2_login(request)
    if provider == 'apple':
        from allauth.socialaccount.providers.apple.views import oauth2_login as apple_oauth2_login
        return apple_oauth2_login(request)

    from django.http import HttpResponseBadRequest
    return HttpResponseBadRequest(f'Unknown provider: {provider}')


def _social_callback_jwt_redirect(request, get_response):
    """
    After provider callback runs (get_response), if user is authenticated,
    generate JWT, flush session, and redirect to frontend with token in fragment.
    """
    response = get_response(request)
    if not request.user.is_authenticated:
        return response
    if response.status_code not in (302, 303):
        return response

    redirect_path = request.session.pop(SOCIAL_REDIRECT_KEY, None) or '/account'
    requested_host = request.session.pop(SOCIAL_HOST_KEY, None)

    refresh = RefreshToken.for_user(request.user)
    access = str(refresh.access_token)
    refresh_str = str(refresh)

    request.session.flush()

    callback_url = _build_callback_url_with_fragment(
        request, access, refresh_str, redirect_path, requested_host=requested_host
    )
    return HttpResponseRedirect(callback_url)


def social_callback_view(request, provider):
    """
    OAuth callback: run provider callback, then replace redirect with JWT fragment redirect.
    """
    if provider == 'google':
        response = _social_callback_jwt_redirect(request, google_oauth2_callback)
    elif provider == 'facebook':
        response = _social_callback_jwt_redirect(request, facebook_oauth2_callback)
    elif provider == 'apple':
        from allauth.socialaccount.providers.apple.views import oauth2_callback as apple_oauth2_callback
        response = _social_callback_jwt_redirect(request, apple_oauth2_callback)
    else:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest(f'Unknown provider: {provider}')

    return response


# Apple sends POST; must exempt CSRF for callback
social_callback_view_csrf_exempt = csrf_exempt(social_callback_view)


# --- Provider discovery -----------------------------------------------------

# Each provider is "enabled" iff the credential fields it actually needs at
# runtime are populated in settings.SOCIALACCOUNT_PROVIDERS. The empty-string
# defaults in settings.py mean unset env vars fall through naturally — no
# extra flag needed to disable a provider.
_PROVIDER_REQUIRED_KEYS = {
    'google': ('client_id', 'secret'),
    'facebook': ('client_id', 'secret'),
    # Apple uses a signed JWT, so it needs the private key on top of the IDs.
    'apple': ('client_id', 'secret', 'key', 'certificate_key'),
}


def _provider_configured(name):
    app = ((getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {}) or {}).get(name) or {}).get('APP') or {}
    required = _PROVIDER_REQUIRED_KEYS.get(name) or ()
    return all((app.get(k) or '').strip() for k in required)


@require_http_methods(['GET'])
def social_providers_view(request):
    """Public — list provider keys the frontend should render a button for.

    Returns ``{"providers": ["google", ...]}``. Used so the auth UI can
    auto-hide buttons for providers whose credentials are not yet provisioned
    in env (e.g. show only Google until Apple/Facebook are wired up).
    """
    providers = [
        name for name in _PROVIDER_REQUIRED_KEYS
        if _provider_configured(name)
    ]
    response = JsonResponse({'providers': providers})
    response['Cache-Control'] = 'public, max-age=60'
    return response

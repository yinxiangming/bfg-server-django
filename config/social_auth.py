# -*- coding: utf-8 -*-
"""
Social login (Google, Apple, Facebook) with JWT bridge.

Stores redirect/host in session on login start; on OAuth callback, generates JWT
and redirects to frontend with token in URL fragment (no session cookie).
"""
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
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


def _get_frontend_base_url(request):
    """Frontend base URL from env (no trailing slash)."""
    base = (getattr(settings, 'FRONTEND_URL', '') or '').strip()
    if not base:
        # Fallback: same host, port 3000 (dev)
        scheme = request.scheme
        host = request.get_host().split(':')[0]
        base = f'{scheme}://{host}:3000'
    return base.rstrip('/')


def _build_callback_url_with_fragment(request, access, refresh, redirect_path):
    """Build frontend /auth/callback URL with access, refresh, redirect in fragment."""
    base = _get_frontend_base_url(request)
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
    request.session.pop(SOCIAL_HOST_KEY, None)

    refresh = RefreshToken.for_user(request.user)
    access = str(refresh.access_token)
    refresh_str = str(refresh)

    request.session.flush()

    callback_url = _build_callback_url_with_fragment(
        request, access, refresh_str, redirect_path
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

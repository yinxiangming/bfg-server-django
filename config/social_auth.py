# -*- coding: utf-8 -*-
"""
Social login (Google, Apple, Facebook) with JWT bridge.

Stores redirect/host in session on login start; on OAuth callback, generates JWT
and redirects to frontend with token in URL fragment (no session cookie).
"""
import json
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from allauth.socialaccount.providers.google.views import (
    oauth2_login as google_oauth2_login,
    oauth2_callback as google_oauth2_callback,
)
from allauth.socialaccount.providers.facebook.views import (
    oauth2_login as facebook_oauth2_login,
    oauth2_callback as facebook_oauth2_callback,
)

from bfg.common.social_apps import (
    remember_social_workspace,
    resolve_social_workspace,
    social_apps_for_workspace,
)


logger = logging.getLogger(__name__)


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
    Start social login: store redirect, host and workspace in session, then
    redirect to the provider. GET from frontend; POST may be used by allauth's
    intermediate form.

    Pinning the workspace here is what makes the callback work. By the time the
    provider redirects back, the request is a top-level navigation to *our* API
    domain carrying none of the tenant headers — the session is the only thing
    still pointing at the storefront the visitor came from, and therefore at the
    OAuth client whose code we are about to exchange.
    """
    from django.http import HttpResponseBadRequest

    data = request.GET if request.method == 'GET' else request.POST
    requested_host = data.get('host', '')
    request.session[SOCIAL_REDIRECT_KEY] = data.get('redirect', '/account')
    request.session[SOCIAL_HOST_KEY] = requested_host
    request.session.modified = True

    workspace = remember_social_workspace(request, extra_host=requested_host)
    if workspace is None:
        logger.warning(
            'Social login start could not resolve a workspace (provider=%s, host=%r)',
            provider, requested_host,
        )
        return HttpResponseBadRequest('Could not determine which site this login is for.')
    if not _provider_configured(request, provider):
        logger.warning(
            'Social login start for unconfigured provider (provider=%s, workspace=%s)',
            provider, workspace.id,
        )
        return HttpResponseBadRequest(f'{provider} sign-in is not configured for this site.')

    if provider == 'google':
        return google_oauth2_login(request)
    if provider == 'facebook':
        return facebook_oauth2_login(request)
    if provider == 'apple':
        from allauth.socialaccount.providers.apple.views import oauth2_login as apple_oauth2_login
        return apple_oauth2_login(request)

    return HttpResponseBadRequest(f'Unknown provider: {provider}')


def _ensure_workspace_membership(request, user, requested_host=None):
    """Give a social-signed-up user a Customer row in the workspace they came from.

    Social sign-up (allauth) only creates the User — nothing ties it to the
    workspace the visitor came from. Without a StaffMember or Customer row,
    :meth:`CustomTokenObtainPairSerializer._resolve_workspace_id` returns None,
    the access token carries no ``workspace_id`` claim, and WorkspaceMiddleware
    rejects every subsequent API call in prod. Creating the Customer here is
    the same lazy ``get_or_create`` the storefront viewsets already do on a
    first cart/review/order — just moved to sign-in so the JWT can carry the
    claim from the very first request.

    ``/api/v1/auth/`` is a public path, so the middleware deliberately leaves
    ``request.workspace`` unset. The workspace comes from the same resolution
    the adapter used to pick the OAuth client, so the Customer row can never
    land in a different workspace than the one the visitor actually signed in
    to.
    """
    try:
        workspace = resolve_social_workspace(request, extra_host=requested_host)
        if not workspace:
            return
        from bfg.common.models import Customer, StaffMember

        if StaffMember.all_objects.filter(workspace=workspace, user=user, is_active=True).exists():
            return
        Customer.all_objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={'is_active': True},
        )
    except Exception:  # noqa: BLE001 — never block a valid login on this
        logger.exception('Failed to ensure workspace membership for social login')


def _issue_jwt_pair(request, user, requested_host=None):
    """Return ``(access, refresh)`` strings for ``user``.

    Uses CustomTokenObtainPairSerializer (not ``RefreshToken.for_user``) so the
    token carries the ``workspace_id`` claim WorkspaceMiddleware requires.
    """
    from config.serializers import CustomTokenObtainPairSerializer

    _ensure_workspace_membership(request, user, requested_host=requested_host)
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    return str(refresh.access_token), str(refresh)


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

    access, refresh_str = _issue_jwt_pair(request, request.user, requested_host=requested_host)

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

# A provider is "enabled" for a workspace iff that workspace has an active,
# fully-populated SocialAuthConfig row for it. Which fields count as
# "fully-populated" is the model's business (Apple needs a signing key that
# Google does not), so this module never re-states the rule.
#
# Display order for the buttons. Data order is alphabetical, which would put
# Apple first and shuffle the auth panel the day a workspace adds a provider.
_PROVIDER_DISPLAY_ORDER = ('google', 'facebook', 'apple')


def _configured_apps(request):
    """``{provider: SocialApp}`` usable by the workspace behind ``request``."""
    workspace = resolve_social_workspace(request)
    return {app.provider: app for app in social_apps_for_workspace(workspace)}


def _provider_configured(request, name):
    return name in _configured_apps(request)


@require_http_methods(['GET'])
def social_providers_view(request):
    """Public — list provider keys the frontend should render a button for.

    Returns ``{"providers": ["google", ...], "google_client_id": "..."}`` for
    *the calling workspace*, so the auth UI hides buttons the shop has not
    provisioned an OAuth client for.

    ``google_client_id`` is the OAuth *Web application* client ID. It is public
    by design — Google Identity Services needs it in the browser to render the
    One Tap prompt — and is only meaningful from origins listed in that client's
    "Authorized JavaScript origins". Blank when Google is not configured.

    The workspace comes from the request headers, so the answer differs per
    caller: the response must never land in a shared cache keyed on URL alone,
    or one shop would be handed another shop's client ID.
    """
    apps = _configured_apps(request)
    providers = [name for name in _PROVIDER_DISPLAY_ORDER if name in apps]
    google = apps.get('google')
    response = JsonResponse({
        'providers': providers,
        'google_client_id': google.client_id if google else '',
    })
    response['Cache-Control'] = 'private, max-age=60'
    response['Vary'] = 'X-Workspace-ID, X-Forwarded-Host, Origin'
    return response


# --- Google One Tap / Sign in with Google (ID token) -------------------------


def _read_google_credential(request):
    """Pull the GIS ``credential`` (an ID token) out of a JSON or form POST."""
    content_type = (request.content_type or '').split(';', 1)[0].strip()
    if content_type == 'application/json':
        try:
            body = json.loads((request.body or b'').decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return ''
        if not isinstance(body, dict):
            return ''
        return (body.get('credential') or '').strip()
    return (request.POST.get('credential') or '').strip()


@csrf_exempt
@require_http_methods(['POST'])
def google_one_tap_view(request):
    """Exchange a Google Identity Services ID token for our JWT pair.

    ``POST {"credential": "<ID token>"}`` — the value Google hands the browser
    callback for One Tap, the rendered "Sign in with Google" button, and
    ``prompt()``. Signature, issuer, audience (our client ID), expiry and jti
    replay are all verified by allauth's provider before any user is touched;
    an unverified token can never reach ``complete_social_login``.

    Unlike the redirect flow this never leaves the page, so the response is
    plain JSON rather than a fragment redirect. Sign-up and sign-in are the
    same call: allauth creates the account on first use
    (``SOCIALACCOUNT_AUTO_SIGNUP``) and links it to an existing local account
    with the same verified email (``SOCIALACCOUNT_EMAIL_AUTHENTICATION``).
    """
    if not _provider_configured(request, 'google'):
        return JsonResponse({'detail': 'Google sign-in is not configured.'}, status=503)

    credential = _read_google_credential(request)
    if not credential:
        return JsonResponse({'detail': 'Missing Google credential.'}, status=400)

    from allauth.exceptions import ImmediateHttpResponse
    from allauth.socialaccount.adapter import get_adapter
    from allauth.socialaccount.helpers import complete_social_login

    provider = get_adapter().get_provider(request, 'google')
    try:
        sociallogin = provider.verify_token(request, {'id_token': credential})
    except Exception:  # noqa: BLE001 — allauth raises ValidationError/OAuth2Error/requests errors
        logger.warning('Google One Tap: credential verification failed', exc_info=True)
        return JsonResponse({'detail': 'Invalid Google credential.'}, status=401)

    is_new_user = not sociallogin.is_existing
    try:
        # Runs allauth's normal sign-up/connect pipeline and session login. Its
        # redirect response is irrelevant here — the session is thrown away
        # below and the caller gets JWTs instead.
        complete_social_login(request, sociallogin)
    except ImmediateHttpResponse:
        # e.g. a signup form or a rejection from an adapter hook — whether the
        # user ended up logged in is decided by the check right below.
        pass
    except Exception:  # noqa: BLE001
        logger.exception('Google One Tap: complete_social_login failed')
        return JsonResponse({'detail': 'Google sign-in failed.'}, status=400)

    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return JsonResponse(
            {'detail': 'Google sign-in could not be completed for this account.'},
            status=403,
        )

    access, refresh = _issue_jwt_pair(request, user)
    request.session.flush()

    return JsonResponse({
        'access': access,
        'refresh': refresh,
        'is_new_user': is_new_user,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
        },
    })

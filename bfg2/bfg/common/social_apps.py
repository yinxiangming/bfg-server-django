# -*- coding: utf-8 -*-
"""Which workspace a social-login request belongs to, and what it may sign in with.

Kept beside the model rather than in the allauth adapter so both halves — which
rows count as usable credentials, and how a request is traced back to a tenant
across a round trip through the provider — can be tested without the host
project's URL conf, and so anything needing a workspace's providers asks one
function rather than reimplementing the query.
"""
import logging

from allauth.socialaccount.models import SocialApp

from bfg.common.middleware import resolve_workspace_for_public_request
from bfg.common.models import SocialAuthConfig, Workspace


logger = logging.getLogger(__name__)

# Workspace pinned at login start and read back on the OAuth callback. That
# callback is a redirect *from the provider*: its Host is our own API domain and
# it carries none of the tenant headers, so the session is the only surviving
# link to the storefront the visitor started on.
SOCIAL_WORKSPACE_KEY = 'social_login_workspace_id'

# Per-request memo. The adapter's list_apps() runs several times while allauth
# builds a provider, and each call would otherwise repeat the lookup.
_REQUEST_CACHE_ATTR = '_social_auth_workspace'


def resolve_social_workspace(request, extra_host=None):
    """The workspace whose OAuth credentials this request should use.

    Session first, then the usual public-request resolution (``X-Workspace-ID``,
    forwarded host, Host). Session-first is safe because the API is a different
    site from every storefront, so a browser fetch never carries our session
    cookie — only the provider's top-level callback redirect does, which is
    exactly the case that needs it.
    """
    if hasattr(request, _REQUEST_CACHE_ATTR):
        return getattr(request, _REQUEST_CACHE_ATTR)

    workspace = _resolve_uncached(request, extra_host=extra_host)
    setattr(request, _REQUEST_CACHE_ATTR, workspace)
    return workspace


def _resolve_uncached(request, extra_host=None):
    session = getattr(request, 'session', None)
    workspace_id = session.get(SOCIAL_WORKSPACE_KEY) if session else None
    if workspace_id:
        workspace = Workspace.objects.filter(pk=workspace_id).first()
        if workspace:
            return workspace
        logger.warning(
            'Social login session names workspace %s, which no longer exists', workspace_id
        )

    return resolve_workspace_for_public_request(request, extra_host=extra_host)


def remember_social_workspace(request, extra_host=None):
    """Pin the current workspace into the session before leaving for the provider.

    Resolved while the tenant is still knowable from the request, so the
    callback does not have to re-derive it from a host that will by then be ours.
    Returns the workspace, or None when the request names no workspace at all.
    """
    workspace = resolve_social_workspace(request, extra_host=extra_host)
    if workspace and getattr(request, 'session', None) is not None:
        request.session[SOCIAL_WORKSPACE_KEY] = workspace.id
        request.session.modified = True
    return workspace


def resolve_social_configs(workspace, provider=None):
    """``{provider: SocialAuthConfig}`` in force for ``workspace``.

    A workspace's own row beats the platform default, and the three states it
    can be in are deliberately distinct:

    * usable (active and complete) — the shop's own client wins;
    * inactive — an explicit opt-out. The provider is off for this shop and it
      does **not** silently fall back to the platform's client, or the switch in
      the admin would do nothing;
    * active but half-filled — an unfinished draft, not a decision. It falls
      back, so starting to type credentials cannot take a working login away.

    With no row at all the platform default applies, which is the case for most
    shops: the redirect flow always returns to our own API domain, so one client
    registered for the platform carries every tenant that has not registered one.
    """
    # "Inherited by every workspace" is not the same as "available to anyone".
    # A request we cannot trace to a tenant gets no login at all: signing someone
    # in here would mint a token with no workspace claim, which the middleware
    # rejects on the very next call — a half-finished account, not a login.
    if workspace is None:
        return {}

    owned = SocialAuthConfig.objects.filter(workspace=workspace)
    platform = SocialAuthConfig.objects.filter(workspace__isnull=True)
    if provider:
        owned = owned.filter(provider=provider)
        platform = platform.filter(provider=provider)

    by_provider = {}
    opted_out = set()
    for config in owned:
        if config.is_usable:
            by_provider[config.provider] = config
        elif not config.is_active:
            opted_out.add(config.provider)

    for config in platform:
        if config.provider in by_provider or config.provider in opted_out:
            continue
        if config.is_usable:
            by_provider[config.provider] = config
    return by_provider


def social_apps_for_workspace(workspace, provider=None):
    """:class:`SocialApp` objects ``workspace`` may sign visitors in with.

    The returned apps are deliberately unsaved. allauth supports that — it drops
    the token's app FK when the app has no pk — and it keeps allauth's own
    ``socialaccount_socialapp`` table out of the picture, so a credential has
    exactly one home.
    """
    apps = []
    for config in resolve_social_configs(workspace, provider=provider).values():
        owner = workspace.name if config.workspace_id else 'platform'
        apps.append(
            SocialApp(
                provider=config.provider,
                name=f'{config.get_provider_display()} ({owner})',
                client_id=config.client_id,
                secret=config.secret,
                key=config.key,
                settings=dict(config.settings or {}),
            )
        )
    return apps

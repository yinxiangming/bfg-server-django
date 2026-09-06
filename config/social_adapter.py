# -*- coding: utf-8 -*-
"""Workspace-aware allauth adapter: OAuth credentials per tenant, not per process.

Every provider credential allauth uses funnels through one method —
``SocialAccountAdapter.list_apps`` — which ``get_app()`` is the sole caller of.
Overriding it here makes the redirect login, the OAuth callback and the One Tap
token exchange all resolve credentials for the workspace the visitor came from,
without any of those views having to know that tenancy exists.

Credentials live in :class:`bfg.common.models.SocialAuthConfig`. There is no
environment fallback by design: one ``GOOGLE_CLIENT_ID`` cannot be right for two
storefronts on two domains, and silently falling back to it would hand a tenant
a login button that fails at Google with ``invalid_client``.
"""
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from bfg.common.social_apps import resolve_social_workspace, social_apps_for_workspace


class WorkspaceSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Resolves provider credentials from the requesting workspace."""

    def list_apps(self, request, provider=None, client_id=None):
        # No request means no tenant — a management command or a check run.
        # Returning nothing is right: there is no such thing as "the" app here.
        if request is None:
            return []

        workspace = resolve_social_workspace(request)
        apps = social_apps_for_workspace(workspace, provider=provider)
        if client_id:
            apps = [app for app in apps if app.client_id == client_id]
        return apps

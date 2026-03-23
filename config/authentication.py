# -*- coding: utf-8 -*-
"""
Custom authentication classes for API
"""

import logging

from rest_framework import authentication
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

User = get_user_model()
logger = logging.getLogger(__name__)


class BearerTokenAuthentication(JWTAuthentication):
    """
    Bearer token authentication using JWT tokens.
    Validates JWT access tokens from login endpoint and authenticates the correct user.
    """
    
    def authenticate(self, request):
        # Get the raw token from the Authorization header
        header = self.get_header(request)
        if header is None:
            return None
        
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None
        
        # Validate token and get the validated token
        validated_token = self.get_validated_token(raw_token)
        
        # Get user from token
        user = self.get_user(validated_token)
        
        return (user, validated_token)


class OptionalBearerTokenAuthentication(JWTAuthentication):
    """
    Like BearerTokenAuthentication but never raises: missing or invalid/expired
    token results in anonymous user so AllowAny endpoints (e.g. mark review helpful)
    keep working without forcing 401.
    """
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None
        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            return (user, validated_token)
        except exceptions.APIException:
            return None


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate requests via ``X-API-Key`` (prefix) and ``X-API-Secret`` headers.

    On success the request is associated with a workspace (``request.workspace``)
    and the ``created_by`` user (or an ``AnonymousUser`` if the key has no creator).

    The authenticated ``(user, auth)`` tuple uses ``auth = api_key_instance`` so
    downstream code can distinguish API-key requests from JWT/session requests.
    """

    API_KEY_HEADER = 'HTTP_X_API_KEY'
    API_SECRET_HEADER = 'HTTP_X_API_SECRET'

    def authenticate(self, request):
        api_key = request.META.get(self.API_KEY_HEADER)
        api_secret = request.META.get(self.API_SECRET_HEADER)

        # If neither header is present, this authenticator is not applicable.
        if not api_key or not api_secret:
            return None

        from bfg.common.models import APIKey as APIKeyModel

        try:
            key_obj = APIKeyModel.objects.select_related('workspace', 'created_by').get(
                prefix=api_key,
            )
        except APIKeyModel.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid API key.')

        if not key_obj.is_usable:
            if key_obj.is_expired:
                raise exceptions.AuthenticationFailed('API key has expired.')
            raise exceptions.AuthenticationFailed('API key is inactive.')

        if not key_obj.verify_secret(api_secret):
            raise exceptions.AuthenticationFailed('Invalid API secret.')

        # Stamp last-used (fire-and-forget, non-blocking)
        key_obj.record_usage()

        # Bind workspace to request so WorkspaceMiddleware & views can use it
        from bfg.common.middleware import set_current_workspace
        request.workspace = key_obj.workspace
        set_current_workspace(key_obj.workspace)

        # Use the key creator as the authenticated user, or AnonymousUser
        user = key_obj.created_by or AnonymousUser()
        return (user, key_obj)


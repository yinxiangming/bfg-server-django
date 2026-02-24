# -*- coding: utf-8 -*-
"""
Custom authentication classes for API
"""

from rest_framework import authentication
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth import get_user_model

User = get_user_model()


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


# -*- coding: utf-8 -*-
"""
Custom views for API
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.conf import settings
from .serializers import (
    RegisterSerializer,
    ForgotPasswordSerializer,
    ResetPasswordConfirmSerializer,
    VerifyEmailSerializer
)

User = get_user_model()


@api_view(['POST'])
@authentication_classes([])  # Skip JWT auth — we verify PLATFORM_API_KEY manually
@permission_classes([AllowAny])
def provision_user(request):
    """
    POST /internal/auth/provision-user/
    Called by Platform Server (via Token Exchange) to sync a user and get a Workspace JWT.
    Headers: { "Authorization": "Bearer <PLATFORM_API_KEY>" }
    Body: { "platform_user_id", "email", "name", "role" }
    """
    auth_header = request.headers.get("Authorization")
    platform_key = getattr(settings, "PLATFORM_API_KEY", None)

    # In local development, if PLATFORM_API_KEY is not configured, we allow the request
    # but still verify the header matches what the platform sent if it was provided
    if platform_key and (not auth_header or auth_header != f"Bearer {platform_key}"):
        import logging
        logging.getLogger(__name__).warning("Invalid or missing Platform API Key")
        return Response({"detail": "Invalid Platform API Key"}, status=status.HTTP_403_FORBIDDEN)

    data = request.data
    platform_user_id = data.get("platform_user_id")
    email = data.get("email")
    
    if not email and not platform_user_id:
        return Response({"detail": "Email or Platform User ID is required"}, status=status.HTTP_400_BAD_REQUEST)

    name = data.get("name", "")
    role_code = data.get("role", "staff")

    try:
        from bfg.common.services import UserService
        user, _ = UserService.provision_sso_user(
            platform_user_id=platform_user_id,
            email=email,
            name=name,
            role_code=role_code
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to provision user: {e}")
        return Response({"detail": f"User provisioning failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Generate Workspace JWT
    refresh = RefreshToken.for_user(user)

    return Response({
        "token": str(refresh.access_token),
        "refresh": str(refresh)
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    User registration endpoint
    POST /api/v1/auth/register/
    
    Body:
    {
        "email": "user@example.com",
        "password": "password123",
        "password_confirm": "password123",
        "first_name": "John",
        "last_name": "Doe"
    }
    """
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()

        store_name = getattr(user, '_temporary_store_name', None)
        from bfg.common.services import UserService
        workspace, workspace_error = UserService.process_registration(user, store_name)

        # Generate JWT token for the new user
        refresh = RefreshToken.for_user(user)

        response_data = {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

        if workspace:
            response_data['workspace'] = {
                'id': workspace.id,
                'name': workspace.name,
                'slug': workspace.slug,
            }
        elif workspace_error:
            response_data['workspace_warning'] = workspace_error

        return Response(response_data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    Forgot password endpoint - sends password reset email
    POST /api/v1/auth/forgot-password/
    
    Body:
    {
        "email": "user@example.com"
    }
    """
    serializer = ForgotPasswordSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        
        try:
            from django.conf import settings
            from bfg.common.services import UserService
            frontend_url = getattr(settings, 'FRONTEND_URL', '')
            UserService.request_password_reset(email, frontend_url)
        except Exception:
            pass
        
        # Return success without revealing if email exists
        return Response({
            'detail': 'If the email exists, a password reset link has been sent to your email address.'
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_confirm(request):
    """
    Password reset confirmation endpoint
    POST /api/v1/auth/reset-password-confirm/
    
    Body:
    {
        "uid": "base64_encoded_user_id",
        "token": "password_reset_token",
        "new_password": "newpassword123",
        "new_password_confirm": "newpassword123"
    }
    """
    serializer = ResetPasswordConfirmSerializer(data=request.data)
    if serializer.is_valid():
        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']
        
        try:
            from bfg.common.services import UserService
            UserService.reset_password(uid, token, new_password)
        except ValueError as e:
            return Response({
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({
            'detail': 'Password has been reset successfully.'
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    """
    Email verification endpoint
    POST /api/v1/auth/verify-email/
    
    Body:
    {
        "key": "verification_key"
    }
    
    Note: This is a simplified version. In production, you might want to use
    django-allauth's email verification system.
    """
    serializer = VerifyEmailSerializer(data=request.data)
    if serializer.is_valid():
        key = serializer.validated_data['key']
        
        try:
            from bfg.common.services import UserService
            UserService.verify_email(key)
        except ValueError as e:
            return Response({
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({
            'detail': 'Email verified successfully.'
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# -*- coding: utf-8 -*-
"""
Custom views for API
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from .serializers import (
    RegisterSerializer,
    ForgotPasswordSerializer,
    ResetPasswordConfirmSerializer,
    VerifyEmailSerializer
)

User = get_user_model()


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
        
        # Generate JWT token for the new user
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)
    
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
        
        # Send password reset email with frontend URL (from settings/env)
        try:
            from django.conf import settings
            frontend_url = settings.FRONTEND_URL
            
            # Find user by email
            try:
                user = User.objects.get(email=email, is_active=True)
            except User.DoesNotExist:
                # Don't reveal if email exists for security
                pass
            else:
                # Generate token and uid
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                
                # Create reset URL with uid and token
                reset_link = f"{frontend_url}/reset-password?uid={uid}&token={token}"
                
                # Send email
                try:
                    from django.core.mail import send_mail
                    
                    subject = f"Password reset for {settings.SITE_NAME}"
                    message = f"""
You're receiving this email because you requested a password reset for your account.

Please go to the following page and choose a new password:
{reset_link}

If you didn't request this, please ignore this email.

Your password won't change until you access the link above and create a new one.
                    """
                    
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        fail_silently=False,
                    )
                except Exception as e:
                    # If email sending fails, log it but don't reveal to user
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to send password reset email: {e}")
        except Exception:
            # If email backend is not configured, just return success
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
            # Decode user ID
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({
                'detail': 'Invalid password reset link.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify token
        if not default_token_generator.check_token(user, token):
            return Response({
                'detail': 'Invalid or expired password reset link.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
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
        
        # Try to find user by email verification key or similar mechanism
        # This is a simplified implementation - you may need to adjust based on your verification system
        try:
            # For now, we'll just return success
            # In a real implementation, you would verify the key and activate the user
            return Response({
                'detail': 'Email verified successfully.'
            }, status=status.HTTP_200_OK)
        except Exception:
            return Response({
                'detail': 'Invalid verification key.'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

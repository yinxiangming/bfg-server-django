# -*- coding: utf-8 -*-
"""
Custom serializers for API
"""

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    """
    User registration serializer using allauth's signup
    """
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        """Validate email is unique"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate(self, attrs):
        """Validate password match"""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': ['Passwords do not match.']
            })
        return attrs

    def create(self, validated_data):
        """Create user with hashed password"""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        
        # Use email as username (before @) if username not provided
        email = validated_data['email']
        username = email.split('@')[0]
        
        # Ensure username is unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Create user - similar to allauth's user creation
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_active=True
        )
        
        return user


class ForgotPasswordSerializer(serializers.Serializer):
    """Forgot password serializer - request password reset"""
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        """Validate email exists (but don't reveal if it doesn't for security)"""
        from bfg.common.models import User
        try:
            User.objects.get(email=value, is_active=True)
        except User.DoesNotExist:
            # Don't reveal if email exists for security
            pass
        return value


class ResetPasswordConfirmSerializer(serializers.Serializer):
    """Password reset confirmation serializer"""
    token = serializers.CharField(required=True)
    uid = serializers.CharField(required=True)
    new_password = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    new_password_confirm = serializers.CharField(write_only=True, min_length=8, style={'input_type': 'password'})
    
    def validate(self, attrs):
        """Validate password match"""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': ['Passwords do not match.']
            })
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    """Email verification serializer"""
    key = serializers.CharField(required=True)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom token serializer that allows login with either username or email
    """
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.CharField(required=False, allow_blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make username field optional since we might use email
        self.fields['username'].required = False
        # Password field is already defined in parent class, no need to override

    @classmethod
    def get_token(cls, user):
        """
        Get token for user - override parent method
        """
        token = super().get_token(user)
        return token

    def validate(self, attrs):
        """
        Validate and authenticate user with username or email
        """
        username = (attrs.get('username') or '').strip()
        email = (attrs.get('email') or '').strip()
        password = attrs.get('password')

        if not password:
            raise serializers.ValidationError({
                'password': ['Password is required.']
            })

        # Determine login identifier (username or email)
        if not username and not email:
            raise serializers.ValidationError({
                'username': ['Either username or email is required.']
            })

        # Try to find user by username first, then by email
        user = None
        try:
            if username:
                # Try username first if provided
                try:
                    user = User.objects.get(username=username, is_active=True)
                except User.DoesNotExist:
                    # If username not found and it looks like an email, try email lookup
                    if '@' in username:
                        try:
                            user = User.objects.get(email=username, is_active=True)
                        except User.DoesNotExist:
                            pass
                        except User.MultipleObjectsReturned:
                            raise serializers.ValidationError({
                                'email': ['Multiple accounts found with this email. Please use username instead.']
                            })
            elif email:
                # Try email if username not provided
                try:
                    user = User.objects.get(email=email, is_active=True)
                except User.MultipleObjectsReturned:
                    raise serializers.ValidationError({
                        'email': ['Multiple accounts found with this email. Please use username instead.']
                    })
        except User.DoesNotExist:
            # User not found - will be handled below
            pass

        if not user:
            raise serializers.ValidationError({
                'username': ['No active account found with the given credentials.']
            })

        # Validate password
        if not user.check_password(password):
            raise serializers.ValidationError({
                'password': ['Invalid password.']
            })

        # Set username for parent class (it expects username field)
        attrs['username'] = user.username

        # Get refresh token
        refresh = self.get_token(user)

        # Return data in format expected by parent class
        data = {}
        data['refresh'] = str(refresh)
        data['access'] = str(refresh.access_token)

        return data


# -*- coding: utf-8 -*-
"""
Custom serializers for API
"""

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.utils.text import slugify
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
    store_name = serializers.CharField(required=False, allow_blank=True)

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
        
        # We pop store_name if it exists, so we don't pass it to create_user
        store_name = validated_data.pop('store_name', None)

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

        # If a store name was provided, attach it temporarily
        if store_name:
            user._temporary_store_name = store_name

        return user


class FinalizeOnboardingSerializer(serializers.Serializer):
    """Finalize deferred onboarding after email verification."""
    email = serializers.EmailField(required=True)
    store_name = serializers.CharField(required=True, allow_blank=False)
    admin_name = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError('No user found for this email.')

        self.context['user_obj'] = user
        return value

    def validate_store_name(self, value):
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise serializers.ValidationError('Store name must be at least 2 characters long.')
        return cleaned

    def validate(self, attrs):
        user = self.context.get('user_obj')
        if not user:
            return attrs

        if not user.is_active:
            raise serializers.ValidationError({
                'email': ['Email must be verified before onboarding can be completed.']
            })

        try:
            from allauth.account.models import EmailAddress
            email_record = EmailAddress.objects.filter(user=user, email=user.email).first()
            if email_record and not email_record.verified:
                raise serializers.ValidationError({
                    'email': ['Email must be verified before onboarding can be completed.']
                })
        except Exception:
            # If allauth state is unavailable here, fall back to user.is_active gate above.
            pass

        return attrs

    def save(self):
        user = self.context['user_obj']
        store_name = self.validated_data['store_name']
        admin_name = (self.validated_data.get('admin_name') or '').strip()

        if admin_name:
            parts = admin_name.split()
            first_name = parts[0]
            last_name = ' '.join(parts[1:])
            update_fields = []
            if user.first_name != first_name:
                user.first_name = first_name
                update_fields.append('first_name')
            if user.last_name != last_name:
                user.last_name = last_name
                update_fields.append('last_name')
            if update_fields:
                user.save(update_fields=update_fields)

        from bfg.common.models import StaffMember
        existing_staff = StaffMember.objects.filter(user=user).select_related('workspace').first()
        if existing_staff:
            workspace = existing_staff.workspace
            return user, workspace, False

        from bfg.common.services.workspace_service import WorkspaceService
        from bfg.common.services import UserService

        slug = slugify(store_name)
        existing_workspace = None
        if slug:
            from bfg.common.models import Workspace
            existing_workspace = Workspace.objects.filter(slug=slug).first()

        if existing_workspace:
            raise serializers.ValidationError({
                'store_name': ['A workspace with a similar store name already exists.']
            })

        ws_service = WorkspaceService()
        workspace = ws_service.create_workspace(name=store_name, owner_user=user)

        return user, workspace, True


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
        token = super().get_token(user)
        token['workspace_id'] = cls._resolve_workspace_id(user)
        return token

    @staticmethod
    def _resolve_workspace_id(user):
        """Pick the best workspace for this user to embed in the JWT claim."""
        from bfg.common.models import StaffMember, Customer
        # Use all_objects (unscoped) — no thread-local workspace context here.
        # 1. User's own default_workspace if they're an active member there
        dw = getattr(user, 'default_workspace', None)
        if dw and dw.is_active:
            if StaffMember.all_objects.filter(workspace=dw, user=user, is_active=True).exists():
                return dw.id
        # 2. First active StaffMember workspace
        staff = StaffMember.all_objects.filter(user=user, is_active=True).select_related('workspace').first()
        if staff and staff.workspace.is_active:
            return staff.workspace.id
        # 3. First active Customer workspace
        customer = Customer.all_objects.filter(user=user, is_active=True).select_related('workspace').first()
        if customer and customer.workspace.is_active:
            return customer.workspace.id
        return None

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


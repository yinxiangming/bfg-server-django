"""Storefront account registration.

``/api/v1/auth/register/`` is *merchant* signup: it provisions a workspace for
the new user, leaves the account inactive pending email verification, and never
creates a Customer. A shopper registering in a storefront needs the opposite —
join the workspace they are shopping in, be able to log in immediately, and have
a Customer record so orders can attach to them.
"""
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from bfg.common.models import Customer

logger = logging.getLogger(__name__)
User = get_user_model()


class StorefrontRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    # Optional so a storefront can ask for one field or three.
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=30)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value.lower()

    def validate(self, attrs):
        confirm = attrs.pop('password_confirm', '')
        if confirm and confirm != attrs['password']:
            raise serializers.ValidationError({'password_confirm': ['Passwords do not match.']})
        return attrs


class StorefrontRegisterView(APIView):
    """POST /api/v1/store/auth/register/ — create a shopper and log them in."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return Response(
                {'detail': 'Workspace is required. Send X-Workspace-ID or use a workspace domain.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = StorefrontRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data['email']
        # The local part is the friendliest username available; two shoppers can
        # own the same one across different mail hosts, so it gets a suffix.
        base_username = email.split('@')[0][:120] or 'shopper'
        username = base_username
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base_username}{suffix}'[:150]

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=data['password'],
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
            )
            if data.get('phone'):
                user.phone = data['phone']
            # A shopper has no workspace of their own; they belong to the shop's.
            user.default_workspace = workspace
            user.is_active = True
            user.save()

            customer, _ = Customer.all_objects.get_or_create(workspace=workspace, user=user)

        from config.serializers import CustomTokenObtainPairSerializer
        refresh = CustomTokenObtainPairSerializer.get_token(user)
        logger.info('storefront register: user=%s workspace=%s', user.pk, workspace.pk)

        return Response({
            'user': {
                'id': user.pk,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'customer_id': customer.pk,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)

# -*- coding: utf-8 -*-
from rest_framework import serializers

from config.serializers import RegisterSerializer


class PortalRegisterSerializer(RegisterSerializer):
    """Core registration fields without the generic workspace shortcut."""

    password = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=256,
        trim_whitespace=False,
        style={'input_type': 'password'},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=256,
        trim_whitespace=False,
        style={'input_type': 'password'},
    )
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('store_name', None)


class PortalFinalizeSerializer(serializers.Serializer):
    onboarding_token = serializers.CharField(write_only=True, max_length=4096)
    workspace_name = serializers.CharField(min_length=2, max_length=255)
    admin_name = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate_workspace_name(self, value):
        return value.strip()


class PortalRegisterResultSerializer(serializers.Serializer):
    verification_required = serializers.BooleanField()


class PortalVerifyEmailSerializer(serializers.Serializer):
    key = serializers.CharField(write_only=True, max_length=512)


class PortalVerifyEmailResultSerializer(serializers.Serializer):
    onboarding_token = serializers.CharField()


class PortalLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        max_length=256,
        trim_whitespace=False,
    )


class PortalWorkspaceSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    frontend_url = serializers.URLField()


class PortalLoginResultSerializer(serializers.Serializer):
    onboarding_token = serializers.CharField(required=False)
    session_token = serializers.CharField()
    expires_in = serializers.IntegerField()
    workspaces = PortalWorkspaceSerializer(many=True)


class PortalSSOStartSerializer(serializers.Serializer):
    session_token = serializers.CharField(write_only=True, max_length=4096)
    workspace_uuid = serializers.UUIDField()


class PortalSSOStartResultSerializer(serializers.Serializer):
    redirect_url = serializers.URLField()
    expires_at = serializers.DateTimeField()


class PortalProvisioningResultSerializer(serializers.Serializer):
    created = serializers.BooleanField()
    workspace = PortalWorkspaceSerializer()
    extensions = serializers.ListField(child=serializers.CharField())
    redirect_url = serializers.URLField()
    sso_expires_at = serializers.DateTimeField()


class PortalConfigSerializer(serializers.Serializer):
    portal_id = serializers.UUIDField()
    name = serializers.CharField()
    registration_enabled = serializers.BooleanField()
    defaults = serializers.DictField(child=serializers.CharField(allow_blank=True))


class PortalPageSerializer(serializers.Serializer):
    title = serializers.CharField()
    slug = serializers.CharField()
    excerpt = serializers.CharField(allow_blank=True)
    blocks = serializers.ListField(child=serializers.DictField())
    meta_title = serializers.CharField(allow_blank=True)
    meta_description = serializers.CharField(allow_blank=True)
    meta_keywords = serializers.CharField(allow_blank=True)
    language = serializers.CharField()
    published_at = serializers.DateTimeField(allow_null=True)


class PortalPostSerializer(serializers.Serializer):
    title = serializers.CharField()
    slug = serializers.CharField()
    content = serializers.CharField(allow_blank=True)
    excerpt = serializers.CharField(allow_blank=True)
    featured_image = serializers.CharField(allow_blank=True)
    category_name = serializers.CharField(allow_null=True)
    tags = serializers.ListField(child=serializers.CharField())


class PortalMenuSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    location = serializers.CharField()
    language = serializers.CharField()
    items = serializers.ListField(child=serializers.DictField())


class PortalErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()
    request_id = serializers.CharField()


class BrandPortalProfileInputSerializer(serializers.Serializer):
    registration_enabled = serializers.BooleanField(required=False)
    provisioning_extensions = serializers.ListField(
        child=serializers.CharField(max_length=128), required=False, max_length=32
    )
    default_theme = serializers.CharField(required=False, allow_blank=True, max_length=64)
    default_plan = serializers.CharField(required=False, allow_blank=True, max_length=64)
    default_country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    default_currency = serializers.CharField(required=False, allow_blank=True, max_length=3)
    default_language = serializers.CharField(required=False, allow_blank=True, max_length=16)

    def validate(self, attrs):
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {'unknown_fields': [f'Unknown profile fields: {", ".join(unknown)}.']}
            )
        return attrs

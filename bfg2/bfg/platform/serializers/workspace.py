# -*- coding: utf-8 -*-
"""
Workspace serializers for Platform views.
"""
from rest_framework import serializers
from django.apps import apps

from bfg.common.models import normalize_hostname, resolve_workspace_public_frontend_base_url
from bfg.common.onboarding.catalog import CURRENCY_PROFILES, SUPPORTED_LANGUAGES


def _safe_workspace_domain(instance):
    try:
        return normalize_hostname(resolve_workspace_public_frontend_base_url(instance).split('://', 1)[-1])
    except Exception:
        return ""


def _safe_workspace_frontend_url(instance):
    try:
        return resolve_workspace_public_frontend_base_url(instance)
    except Exception:
        return None


def _reject_domain(initial_data):
    """Refuse a ``domain`` in the request body instead of ignoring it.

    A hostname is unique across the install and decides which workspace a
    storefront request is served by, so binding one takes more than a field
    write: these endpoints cannot tell whether the caller controls the hostname.
    Refusing the field outright also keeps an old client from believing a domain
    was saved.
    """
    if initial_data is not None and 'domain' in initial_data:
        raise serializers.ValidationError({
            'domain': ['Custom domains cannot be set through this endpoint.'],
        })


def _serialize_workspace_profile(instance):
    profile = getattr(instance, "platform_profile", None)
    cluster = getattr(profile, "cluster", None) if profile else None
    return {
        "region": getattr(profile, "region", None),
        "remote_workspace_uuid": (
            str(profile.remote_workspace_uuid)
            if profile and getattr(profile, "remote_workspace_uuid", None)
            else None
        ),
        "suspended_at": getattr(profile, "suspended_at", None) if profile else None,
        "workspace_api_url": getattr(cluster, "api_base_url", None) if cluster else None,
        "workspace_frontend_url": _safe_workspace_frontend_url(instance),
        "cluster": {
            "id": cluster.id,
            "name": cluster.name,
            "region": cluster.region,
            "api_base_url": cluster.api_base_url,
            "frontend_base_url": cluster.frontend_base_url,
            "is_active": cluster.is_active,
        } if cluster else None,
    }


class WorkspaceListSerializer(serializers.Serializer):
    """Read-only workspace list item."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        return {
            'id': instance.id,
            'name': instance.name,
            'slug': instance.slug,
            'domain': _safe_workspace_domain(instance),
            'is_active': instance.is_active,
            'created_at': instance.created_at,
        }


class WorkspaceCreateSerializer(serializers.Serializer):
    """What creating a workspace accepts. Custom domains are bound elsewhere, never here.

    Only ``name`` is required; the other fields may be left out, blank or null, and
    come out as ``""``. A blank ``slug`` is made from the name, and a blank
    ``country``, ``currency`` or ``language`` is left to ``create_owned_workspace``.
    """
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=100, required=False, allow_blank=True, allow_null=True)
    region = serializers.ChoiceField(choices=["us", "eu", "apac"], default="us")
    country = serializers.RegexField(
        r"^[A-Za-z]{2}$", required=False, allow_blank=True, allow_null=True,
        error_messages={"invalid": "Enter a two-letter country code."},
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, allow_null=True)
    language = serializers.CharField(max_length=10, required=False, allow_blank=True, allow_null=True)

    def validate_slug(self, value):
        # A slug the caller picked is refused when taken, never quietly changed.
        value = value or ""
        Workspace = apps.get_model("common", "Workspace")
        if value and Workspace.objects.filter(slug=value).exists():
            raise serializers.ValidationError("This slug is already taken.")
        return value

    def validate_country(self, value):
        return (value or "").upper()

    def validate_currency(self, value):
        # Currency rows are shared by every workspace, so only a currency the
        # platform has a profile for is taken.
        code = (value or "").strip().upper()
        if code and code not in CURRENCY_PROFILES:
            raise serializers.ValidationError("Unsupported currency.")
        return code

    def validate_language(self, value):
        code = (value or "").strip().lower()
        if code and code not in SUPPORTED_LANGUAGES:
            raise serializers.ValidationError("Unsupported language.")
        return code

    def validate(self, attrs):
        _reject_domain(getattr(self, 'initial_data', None))
        return attrs


class WorkspaceDetailSerializer(serializers.Serializer):
    """Read/update workspace details. ``domain`` is read-only here."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(read_only=True)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=50, required=False)
    is_active = serializers.BooleanField(read_only=True)
    settings = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate(self, attrs):
        _reject_domain(getattr(self, 'initial_data', None))
        return attrs

    def to_representation(self, instance):
        return {
            'id': instance.id,
            'name': instance.name,
            'slug': instance.slug,
            'domain': _safe_workspace_domain(instance),
            'email': instance.email,
            'phone': instance.phone,
            'is_active': instance.is_active,
            'settings': instance.settings,
            'created_at': instance.created_at,
            'updated_at': instance.updated_at,
            'workspace_profile': _serialize_workspace_profile(instance),
        }

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

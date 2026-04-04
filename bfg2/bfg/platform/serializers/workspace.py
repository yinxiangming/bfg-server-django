# -*- coding: utf-8 -*-
"""
Workspace serializers for Platform views.
"""
from rest_framework import serializers
from django.apps import apps


class WorkspaceListSerializer(serializers.Serializer):
    """Read-only workspace list item."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    domain = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class WorkspaceCreateSerializer(serializers.Serializer):
    """Create a new workspace."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=100)
    domain = serializers.CharField(max_length=255, required=False, default="")
    region = serializers.ChoiceField(choices=["us", "eu", "apac"], default="us")

    def validate_slug(self, value):
        Workspace = apps.get_model("common", "Workspace")
        if Workspace.objects.filter(slug=value).exists():
            raise serializers.ValidationError("This slug is already taken.")
        return value

    def create(self, validated_data):
        region = validated_data.pop("region", "us")
        request = self.context.get('request')
        user = request.user if request else None

        from bfg.common.services.workspace_service import WorkspaceService
        service = WorkspaceService(user=user)

        workspace = service.create_workspace(
            name=validated_data.get('name'),
            slug=validated_data.get('slug'),
            owner_user=user,
            domain=validated_data.get('domain', '')
        )
        
        # Attach region dynamically so the serializer can return it in .data if requested
        workspace.region = region
        return workspace

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "uuid": str(instance.uuid) if hasattr(instance, "uuid") and instance.uuid else None,
            "name": instance.name,
            "slug": instance.slug,
            "domain": getattr(instance, "domain", ""),
            "region": getattr(instance, "region", "us"),
            "is_active": getattr(instance, "is_active", True),
        }


class WorkspaceDetailSerializer(serializers.Serializer):
    """Read/update workspace details."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(read_only=True)
    domain = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=50, required=False)
    is_active = serializers.BooleanField(read_only=True)
    settings = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

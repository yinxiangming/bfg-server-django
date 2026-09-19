# -*- coding: utf-8 -*-
"""
Workspace serializers for Platform views.
"""
from rest_framework import serializers
from django.apps import apps

from bfg.common.exceptions import WorkspaceCapacityUnavailable
from bfg.common.models import normalize_hostname, resolve_workspace_public_frontend_base_url


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


def _validate_domain_assignment(hostname, workspace=None):
    """Reject attempts to move another workspace's hostname."""
    normalized = normalize_hostname(hostname)
    if not normalized:
        return normalized
    WorkspaceDomain = apps.get_model("common", "WorkspaceDomain")
    existing = WorkspaceDomain.objects.filter(hostname=normalized).first()
    if existing and (workspace is None or existing.workspace_id != workspace.id):
        raise serializers.ValidationError(
            "This domain is already assigned to another workspace."
        )
    return normalized


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

    def validate_domain(self, value):
        return _validate_domain_assignment(value)

    def create(self, validated_data):
        region = validated_data.pop("region", "us")
        request = self.context.get('request')
        user = request.user if request else None

        from bfg.common.services.workspace_service import WorkspaceService
        service = WorkspaceService(user=user)

        try:
            workspace = service.create_workspace(
                name=validated_data.get('name'),
                slug=validated_data.get('slug'),
                owner_user=user,
                region=region,
            )
        except WorkspaceCapacityUnavailable as exc:
            # This is expected operational state, not an unhandled service error.
            raise serializers.ValidationError({
                'code': exc.default_code,
                'detail': str(exc),
            }) from exc

        hostname = validated_data.get('domain', '')
        if hostname:
            WorkspaceDomain = apps.get_model('common', 'WorkspaceDomain')
            WorkspaceDomain.objects.create(
                hostname=hostname,
                workspace=workspace,
                kind=WorkspaceDomain.KIND_CUSTOM,
                # A browser request cannot prove control of a hostname. Verification
                # must complete before a custom domain becomes primary.
                verification_status=WorkspaceDomain.VERIFICATION_PENDING,
                ssl_status=WorkspaceDomain.SSL_NONE,
                is_primary=False,
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
            "domain": _safe_workspace_domain(instance),
            "region": getattr(instance, "region", "us"),
            "is_active": getattr(instance, "is_active", True),
        }


class WorkspaceDetailSerializer(serializers.Serializer):
    """Read/update workspace details."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(read_only=True)
    domain = serializers.CharField(
        max_length=255, required=False, allow_blank=True, write_only=True
    )
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(max_length=50, required=False)
    is_active = serializers.BooleanField(read_only=True)
    settings = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_domain(self, value):
        return _validate_domain_assignment(value, workspace=self.instance)

    def to_representation(self, instance):
        profile = getattr(instance, 'platform_profile', None)
        cluster = getattr(profile, 'cluster', None) if profile else None
        request = self.context.get('request')
        viewer_id = getattr(getattr(request, 'user', None), 'id', None)
        from bfg.platform.utils import is_embedded_mode, is_platform_workspace

        if is_embedded_mode():
            StaffMember = apps.get_model('common', 'StaffMember')
            memberships = StaffMember.all_objects.filter(
                workspace=instance, is_active=True,
            )
            owner_membership = (
                memberships.filter(role__code__in=['owner', 'admin'])
                .select_related('user')
                .order_by('id')
                .first()
            )
        else:
            PlatformMembership = apps.get_model('platform', 'PlatformMembership')
            memberships = PlatformMembership.objects.filter(
                profile__workspace=instance, is_active=True,
            )
            owner_membership = (
                memberships.filter(role='owner')
                .select_related('user')
                .order_by('id')
                .first()
            )
        owner = None
        if owner_membership:
            owner_user = owner_membership.user
            owner = {
                'id': owner_user.id,
                'username': owner_user.username,
                'email': owner_user.email or None,
            }

        return {
            'id': instance.id,
            'name': instance.name,
            'slug': instance.slug,
            'domain': _safe_workspace_domain(instance),
            'domains': list(instance.domains.values_list('hostname', flat=True)),
            'email': instance.email,
            'phone': instance.phone,
            'is_active': instance.is_active,
            'is_platform': is_platform_workspace(instance),
            'suspended_at': getattr(profile, 'suspended_at', None),
            'settings': instance.settings,
            'created_at': instance.created_at,
            'updated_at': instance.updated_at,
            'workspace_profile': _serialize_workspace_profile(instance),
            'cluster': {
                'id': cluster.id,
                'name': cluster.name,
                'region': cluster.region,
                'is_active': cluster.is_active,
            } if cluster else None,
            'owner': owner,
            'owned_by_viewer': bool(owner and owner['id'] == viewer_id),
            'staff_count': memberships.count(),
            # Workspace extensions and metered usage are not persisted by this
            # backend yet. Keep owner detail stable and advertise that boundary.
            'active_extensions': [],
            'extensions': [],
            'capabilities': {
                'extension_management': False,
                'usage': False,
            },
        }

    def update(self, instance, validated_data):
        domain = validated_data.pop('domain', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if domain is not None:
            WorkspaceDomain = apps.get_model('common', 'WorkspaceDomain')
            hostname = domain
            if hostname:
                existing = WorkspaceDomain.objects.filter(hostname=hostname).first()
                if existing:
                    # An already verified domain owned by this workspace may be made
                    # primary. An unverified hostname remains pending and does not
                    # displace the reachable current domain.
                    if existing.verification_status == WorkspaceDomain.VERIFICATION_VERIFIED:
                        instance.domains.filter(
                            kind=WorkspaceDomain.KIND_CUSTOM,
                            is_primary=True,
                        ).exclude(pk=existing.pk).update(is_primary=False)
                        existing.kind = WorkspaceDomain.KIND_CUSTOM
                        existing.is_primary = True
                        existing.save(update_fields=['kind', 'is_primary'])
                else:
                    WorkspaceDomain.objects.create(
                        hostname=hostname,
                        workspace=instance,
                        kind=WorkspaceDomain.KIND_CUSTOM,
                        verification_status=WorkspaceDomain.VERIFICATION_PENDING,
                        ssl_status=WorkspaceDomain.SSL_NONE,
                        is_primary=False,
                    )
        return instance

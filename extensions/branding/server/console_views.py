# -*- coding: utf-8 -*-
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from bfg.common.extensions import (
    ACTIVATION_WORKSPACE_OWNER,
    VISIBILITY_PUBLIC,
    registry,
    services as extension_services,
)
from bfg.common.models import Workspace, WorkspaceDomain
from bfg.platform.services.workspace_service import is_platform_admin

from .models import BrandPortalProfile, BrandPortalProvisioning
from .serializers import BrandPortalProfileInputSerializer
from .services import PROFILE_FIELDS, save_profile


class IsPlatformAdministrator(BasePermission):
    message = 'Only a platform administrator can manage brand portals.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated) and is_platform_admin(
            request.user
        )


class BrandPortalConsoleView(APIView):
    """Platform-only profile and audit view for one brand workspace."""

    permission_classes = [IsPlatformAdministrator]

    def get(self, request, workspace_id):
        workspace = get_object_or_404(
            Workspace.objects.select_related('platform_profile'), pk=workspace_id
        )
        return Response(self._payload(workspace))

    def patch(self, request, workspace_id):
        workspace = get_object_or_404(
            Workspace.objects.select_related('platform_profile'), pk=workspace_id
        )
        blocked = self._blocked(workspace)
        if blocked:
            return Response(blocked, status=status.HTTP_409_CONFLICT)
        if not extension_services.is_available(workspace, 'brand_portal'):
            return Response(
                {
                    'code': 'portal_extension_inactive',
                    'detail': 'Activate the brand portal extension before configuring it.',
                },
                status=status.HTTP_409_CONFLICT,
            )
        serializer = BrandPortalProfileInputSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {
                    'code': 'invalid_portal_profile',
                    'detail': 'The brand portal profile is invalid.',
                    'errors': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            save_profile(workspace, serializer.validated_data, actor=request.user)
        except DjangoValidationError as exc:
            return Response(
                {
                    'code': 'invalid_portal_profile',
                    'detail': 'The brand portal profile is invalid.',
                    'errors': getattr(exc, 'message_dict', {'profile': exc.messages}),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self._payload(workspace))

    @staticmethod
    def _blocked(workspace):
        profile = getattr(workspace, 'platform_profile', None)
        if profile and profile.suspended_at:
            return {
                'code': 'workspace_suspended',
                'detail': 'A suspended workspace cannot change its brand portal profile.',
            }
        if not workspace.is_active:
            return {
                'code': 'workspace_inactive',
                'detail': 'An inactive workspace cannot change its brand portal profile.',
            }
        return None

    @classmethod
    def _payload(cls, workspace):
        profile = BrandPortalProfile.objects.filter(workspace=workspace).first()
        profile_data = (
            {
                'configured': True,
                'public_id': str(profile.public_id),
                **{field: getattr(profile, field) for field in PROFILE_FIELDS},
                'updated_at': profile.updated_at,
            }
            if profile
            else {
                'configured': False,
                'public_id': None,
                **{
                    field: ([] if field == 'provisioning_extensions' else False if field == 'registration_enabled' else '')
                    for field in PROFILE_FIELDS
                },
                'updated_at': None,
            }
        )
        domains = list(
            WorkspaceDomain.objects.filter(
                workspace=workspace,
                verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
            )
            .order_by('-is_primary', 'kind', 'hostname')
            .values('hostname', 'kind', 'is_primary', 'ssl_status')
        )
        recent = [
            {
                'id': item.pk,
                'status': item.status,
                'target_workspace': (
                    {
                        'uuid': str(item.target_workspace.uuid),
                        'name': item.target_workspace.name,
                        'slug': item.target_workspace.slug,
                    }
                    if item.target_workspace
                    else None
                ),
                'error_code': item.error_code,
                'created_at': item.created_at,
                'completed_at': item.completed_at,
            }
            for item in BrandPortalProvisioning.objects.filter(portal_workspace=workspace)
            .select_related('target_workspace')
            .order_by('-created_at', '-id')[:20]
        ]
        options = [
            {
                'key': manifest.key,
                'name': str(manifest.name),
                'name_zh': str(manifest.name_zh),
            }
            for manifest in registry.all_manifests()
            if manifest.is_activatable
            and manifest.visibility == VISIBILITY_PUBLIC
            and manifest.activation_policy == ACTIVATION_WORKSPACE_OWNER
        ]
        return {
            'workspace': {
                'id': workspace.pk,
                'name': workspace.name,
                'is_active': workspace.is_active,
                'suspended': bool(
                    getattr(getattr(workspace, 'platform_profile', None), 'suspended_at', None)
                ),
            },
            'extension_active': extension_services.is_available(workspace, 'brand_portal'),
            'profile': profile_data,
            'extension_options': options,
            'verified_domains': domains,
            'recent_provisionings': recent,
        }

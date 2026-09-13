# -*- coding: utf-8 -*-
"""
The extension API a workspace's own staff use.

GET   /api/v1/extensions/                  extensions this deployment offers, with the workspace's state
POST  /api/v1/extensions/<key>/activate/   optional body: {"config": {...}}
POST  /api/v1/extensions/<key>/deactivate/
PATCH /api/v1/extensions/<key>/config/     body: {"config": {...}}

Any staff member can read; changes need a workspace administrator, who is also the
only one shown each extension's configuration.
"""

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from bfg.common.extensions import registry, services
from bfg.core.permissions import IsWorkspaceAdmin, StaffReadAdminWrite

logger = logging.getLogger(__name__)


def _unmet_prerequisites(manifest, workspace):
    # A prerequisite check that raises is reported as unmet, so one broken check
    # cannot take the whole extension list down with it.
    unmet = []
    for prerequisite in manifest.prerequisites:
        try:
            met = prerequisite.is_met(workspace)
        except Exception:
            logger.exception('Prerequisite %s of extension %s failed', prerequisite.code, manifest.key)
            met = False
        if not met:
            unmet.append(prerequisite.message)
    return unmet


def serialize_extension(manifest, record, available, workspace, include_config=False):
    from bfg.common.models import WorkspaceExtension

    payload = {
        'key': manifest.key,
        'name': str(manifest.name),
        'description': str(manifest.description),
        'pricing': manifest.pricing,
        'surfaces': list(manifest.surfaces),
        'requires': list(manifest.requires),
        'meters': list(manifest.meters),
        'config_schema': manifest.config_schema,
        'status': record.status if record else WorkspaceExtension.STATUS_INACTIVE,
        'status_reason': record.status_reason if record else '',
        'status_changed_at': record.status_changed_at if record else None,
        'available': manifest.key in available,
        'unmet_prerequisites': _unmet_prerequisites(manifest, workspace),
    }
    if include_config:
        payload['config'] = record.config if record else {}
    return payload


class ExtensionViewSet(viewsets.ViewSet):
    permission_classes = [StaffReadAdminWrite]
    lookup_field = 'key'
    lookup_value_regex = r'[a-z][a-z0-9_]*'

    def list(self, request):
        from bfg.common.models import WorkspaceExtension

        workspace = request.workspace
        records = {record.key: record for record in WorkspaceExtension.all_objects.filter(workspace=workspace)}
        available = services.compute_available_keys(workspace)
        include_config = IsWorkspaceAdmin().has_permission(request, self)
        return Response([
            serialize_extension(manifest, records.get(manifest.key), available, workspace, include_config)
            for manifest in registry.all_manifests()
            if manifest.is_activatable
        ])

    @action(detail=True, methods=['post'])
    def activate(self, request, key=None):
        config = request.data.get('config') if hasattr(request.data, 'get') else None
        return self._change(
            request, key, lambda: services.activate(request.workspace, key, user=request.user, config=config)
        )

    @action(detail=True, methods=['post'])
    def deactivate(self, request, key=None):
        return self._change(request, key, lambda: services.deactivate(request.workspace, key, user=request.user))

    @action(detail=True, methods=['patch'])
    def config(self, request, key=None):
        if not hasattr(request.data, 'get') or 'config' not in request.data:
            return Response(
                {'code': 'invalid_config', 'detail': 'Send the configuration as {"config": {...}}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._change(
            request,
            key,
            lambda: services.update_config(request.workspace, key, request.data['config']),
        )

    def _change(self, request, key, change):
        try:
            record = change()
        except services.ExtensionError as exc:
            http_status = (
                status.HTTP_404_NOT_FOUND if exc.code == 'unknown_extension' else status.HTTP_400_BAD_REQUEST
            )
            return Response({'code': exc.code, 'detail': exc.message, **exc.details}, status=http_status)
        available = services.compute_available_keys(request.workspace)
        return Response(
            serialize_extension(registry.get_manifest(key), record, available, request.workspace, include_config=True)
        )

"""
Store ViewSet
"""
from django.db import IntegrityError

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bfg.core.permissions import IsWorkspaceAdmin
from bfg.shop.models import Store
from bfg.shop.serializers import StoreSerializer


class StoreViewSet(viewsets.ModelViewSet):
    """Store management ViewSet (Admin only)"""
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]

    def get_queryset(self):
        """Get stores for current workspace"""
        if getattr(self.request, 'workspace', None) is None:
            return Store.objects.none()
        return Store.objects.filter(
            workspace=self.request.workspace
        ).prefetch_related('warehouses')

    def create(self, request, *args, **kwargs):
        """Create store; return 400 when workspace missing, 409 on duplicate."""
        if getattr(request, 'workspace', None) is None:
            return Response(
                {'detail': 'No workspace available.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as e:
            msg = str(e.args[1]) if len(e.args) > 1 else 'Duplicate or invalid store.'
            if 'cannot be null' in msg or 'workspace_id' in msg:
                return Response(
                    {'detail': 'No workspace available.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response(
                {'detail': msg or 'A store with this code already exists for this workspace.'},
                status=status.HTTP_409_CONFLICT
            )

    def perform_create(self, serializer):
        """Create store with workspace"""
        if getattr(self.request, 'workspace', None) is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("No workspace available.")
        serializer.save(workspace=self.request.workspace)


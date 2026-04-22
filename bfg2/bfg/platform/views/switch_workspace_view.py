# -*- coding: utf-8 -*-
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from bfg.common.models import Workspace, StaffMember, Customer


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def switch_workspace(request):
    """
    POST /api/v1/platform/switch-workspace/
    Body: {"workspace_id": 42}

    Mint a new JWT pair with workspace_id claim for the requested workspace.
    Requires active StaffMember or Customer membership.
    """
    workspace_id = request.data.get('workspace_id')
    if not workspace_id:
        return Response({'detail': 'workspace_id is required', 'code': 'workspace_id_required'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        workspace = Workspace.objects.get(id=int(workspace_id), is_active=True)
    except (Workspace.DoesNotExist, ValueError, TypeError):
        return Response({'detail': 'Workspace not found or inactive.', 'code': 'workspace_not_found'},
                        status=status.HTTP_404_NOT_FOUND)

    user = request.user
    is_member = (
        StaffMember.all_objects.filter(workspace=workspace, user=user, is_active=True).exists()
        or Customer.all_objects.filter(workspace=workspace, user=user, is_active=True).exists()
    )
    if not is_member:
        return Response({'detail': 'You are not a member of this workspace.', 'code': 'workspace_access_denied'},
                        status=status.HTTP_403_FORBIDDEN)

    refresh = RefreshToken.for_user(user)
    refresh['workspace_id'] = workspace.id

    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'workspace': {
            'id': workspace.id,
            'slug': workspace.slug,
            'name': workspace.name,
        },
    })

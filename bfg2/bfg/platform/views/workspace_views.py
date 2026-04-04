# -*- coding: utf-8 -*-
"""
Platform Workspace ViewSet.
Follows BFG standard: ModelViewSet + @action decorators.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.apps import apps

from bfg.platform.services.workspace_service import get_user_workspaces, is_platform_admin
from bfg.platform.services.provision_service import provision_workspace, suspend_workspace, resume_workspace
from bfg.platform.services.subscription_service import SubscriptionService
from bfg.platform.permissions import IsWorkspaceOwner, IsPlatformAdmin
from bfg.platform.serializers.workspace import (
    WorkspaceListSerializer,
    WorkspaceCreateSerializer,
    WorkspaceDetailSerializer,
)
from bfg.platform.serializers.subscription import SubscriptionSerializer
from bfg.platform.serializers.subscription_plan import SubscriptionPlanSerializer


class WorkspaceViewSet(viewsets.ModelViewSet):
    """
    Workspace management for Platform.

    list:   GET  /api/v1/platform/workspaces/          — user's workspaces
    create: POST /api/v1/platform/workspaces/          — create new workspace
    retrieve: GET /api/v1/platform/workspaces/{id}/
    update: PATCH /api/v1/platform/workspaces/{id}/

    @actions:
      POST /api/v1/platform/workspaces/{id}/suspend/
      POST /api/v1/platform/workspaces/{id}/resume/
      GET  /api/v1/platform/workspaces/{id}/subscription/
      POST /api/v1/platform/workspaces/{id}/checkout/
      GET  /api/v1/platform/me/                        — my workspaces + platform admin flag
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'create':
            return WorkspaceCreateSerializer
        if self.action in ('retrieve', 'partial_update'):
            return WorkspaceDetailSerializer
        return WorkspaceListSerializer

    def get_queryset(self):
        StaffMember = apps.get_model('common', 'StaffMember')
        Workspace = apps.get_model('common', 'Workspace')
        workspace_ids = StaffMember.objects.filter(
            user=self.request.user, is_active=True
        ).values_list('workspace_id', flat=True)
        return Workspace.objects.filter(id__in=workspace_ids)

    def perform_create(self, serializer):
        workspace = serializer.save()

        provision_workspace.delay(
            workspace_id=workspace.id,
            initiated_by_id=self.request.user.id,
        )

    # ── Custom actions ───────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        """GET /api/v1/platform/workspaces/me/ — current user's workspace list."""
        return Response({
            'workspaces': get_user_workspaces(request.user),
            'is_platform_admin': is_platform_admin(request.user),
        })

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        """POST /api/v1/platform/workspaces/{id}/suspend/"""
        workspace = self.get_object()
        suspend_workspace(
            workspace,
            initiated_by=request.user,
            reason=request.data.get('reason', ''),
        )
        return Response({'status': 'suspended'})

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """POST /api/v1/platform/workspaces/{id}/resume/"""
        workspace = self.get_object()
        resume_workspace(workspace, initiated_by=request.user)
        return Response({'status': 'active'})

    @action(detail=True, methods=['get'])
    def subscription(self, request, pk=None):
        """GET /api/v1/platform/workspaces/{id}/subscription/"""
        workspace = self.get_object()
        Subscription = apps.get_model('shop', 'Subscription')
        sub = Subscription.objects.filter(
            workspace=workspace
        ).select_related('plan', 'customer').order_by('-created_at').first()
        if not sub:
            return Response({'subscription': None})
        return Response({'subscription': SubscriptionSerializer(sub).data})

    @action(detail=True, methods=['post'])
    def checkout(self, request, pk=None):
        """POST /api/v1/platform/workspaces/{id}/checkout/"""
        workspace = self.get_object()
        SubscriptionPlan = apps.get_model('shop', 'SubscriptionPlan')

        plan_id = request.data.get('plan_id')
        billing_interval = request.data.get('billing_interval', 'monthly')

        try:
            plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            url = SubscriptionService().create_checkout(
                workspace=workspace,
                plan=plan,
                billing_interval=billing_interval,
                user=request.user,
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'checkout_url': url})


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Subscription plan listing (public — for pricing page).

    list:     GET /api/v1/platform/plans/
    retrieve: GET /api/v1/platform/plans/{id}/
    """
    permission_classes = [AllowAny]
    serializer_class = SubscriptionPlanSerializer

    def get_queryset(self):
        SubscriptionPlan = apps.get_model('shop', 'SubscriptionPlan')
        return SubscriptionPlan.objects.filter(is_active=True).order_by('price')


class SSOConfigViewSet(viewsets.ViewSet):
    """
    SSO configuration views.

    @actions:
      GET  /api/v1/platform/sso/check/                — check domain SSO
      GET  /api/v1/platform/sso/google/callback/
      GET  /api/v1/platform/sso/azure/callback/
    """
    permission_classes = [AllowAny]

    @action(detail=False, methods=['get'], url_path='check')
    def check(self, request):
        """GET /api/v1/platform/sso/check/?domain=acme.com"""
        from bfg.platform.views.auth_views import SSOCheckView
        return SSOCheckView().get(request)

    @action(detail=False, methods=['get'], url_path='google/callback')
    def google_callback(self, request):
        from bfg.platform.views.auth_views import GoogleSSOCallbackView
        return GoogleSSOCallbackView().get(request)

    @action(detail=False, methods=['get'], url_path='azure/callback')
    def azure_callback(self, request):
        from bfg.platform.views.auth_views import AzureSSOCallbackView
        return AzureSSOCallbackView().get(request)

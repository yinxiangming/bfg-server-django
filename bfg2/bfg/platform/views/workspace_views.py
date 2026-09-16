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
from django.db.models import Q

from bfg.common.exceptions import WorkspaceAlreadyExists
from bfg.core.read_only import exempt_from_read_only
from bfg.platform.services.ownership import owned_workspace_ids
from bfg.platform.services.workspace_creation import (
    WorkspaceCreateForbidden,
    WorkspaceLimitReached,
    create_owned_workspace,
    ensure_workspace_create_allowed,
    max_owned_workspaces,
    workspace_create_blocked,
)
from bfg.platform.services.workspace_service import get_user_workspace, get_user_workspaces, is_platform_admin
from bfg.platform.services.provision_service import suspend_workspace, resume_workspace
from bfg.platform.services.subscription_service import SubscriptionService
from bfg.platform.permissions import IsWorkspaceOwner, IsPlatformAdmin
from bfg.platform.utils import get_platform_workspace, is_embedded_mode
from bfg.platform.serializers.workspace import (
    WorkspaceListSerializer,
    WorkspaceCreateSerializer,
    WorkspaceDetailSerializer,
)
from bfg.platform.serializers.subscription import SubscriptionSerializer
from bfg.platform.serializers.subscription_plan import SubscriptionPlanSerializer


def _token_workspace_id(request):
    """The ``workspace_id`` claim of the caller's access token, if the request carries one.

    Platform paths bind no workspace to the request, so the claim is the only
    word on which workspace the caller is working in. A session or an API key
    has none.
    """
    payload = getattr(request.auth, 'payload', None)
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get('workspace_id'))
    except (TypeError, ValueError):
        return None


class WorkspaceViewSet(viewsets.ModelViewSet):
    """
    Workspace management for Platform.

    list:   GET  /api/v1/platform/workspaces/          — workspaces the user is staff of or owns
    create: POST /api/v1/platform/workspaces/          — owners and admins of a workspace, up to a limit of owned ones
    retrieve: GET /api/v1/platform/workspaces/{id}/
    update: PATCH /api/v1/platform/workspaces/{id}/    — owner only: name, email, phone; never a custom domain

    @actions:
      POST /api/v1/platform/workspaces/{id}/suspend/   — platform admins only
      POST /api/v1/platform/workspaces/{id}/resume/    — platform admins only
      GET  /api/v1/platform/workspaces/{id}/subscription/
      POST /api/v1/platform/workspaces/{id}/checkout/
      GET  /api/v1/platform/workspaces/me/             — my workspaces, platform admin flag, whether I may create one
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'create':
            return WorkspaceCreateSerializer
        if self.action in ('retrieve', 'partial_update'):
            return WorkspaceDetailSerializer
        return WorkspaceListSerializer

    def get_permissions(self):
        # The queryset lets every staff role reach a workspace, but renaming it
        # or changing its contact details is for its owner.
        if self.action in ('update', 'partial_update'):
            return [IsAuthenticated(), IsWorkspaceOwner()]
        return super().get_permissions()

    def get_queryset(self):
        StaffMember = apps.get_model('common', 'StaffMember')
        Workspace = apps.get_model('common', 'Workspace')
        user = self.request.user
        # Cross-workspace lookup — must use ``all_objects`` so the platform
        # endpoint sees every workspace the user belongs to, not just the
        # one bound to the current request.
        workspace_ids = StaffMember.all_objects.filter(
            user=user, is_active=True,
        ).values_list('workspace_id', flat=True)
        # An owner reaches their workspace without being staff of it, and
        # while it is suspended or inactive.
        owned_ids = owned_workspace_ids(user)
        # Newest first so freshly-provisioned workspaces appear on page 1
        # without the caller having to paginate or sort. The Workspace
        # model defaults to ordering by ``name`` (alphabetical) which is
        # surprising on a "my workspaces" view.
        return Workspace.objects.filter(
            Q(id__in=workspace_ids) | Q(id__in=owned_ids),
        ).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        """POST /api/v1/platform/workspaces/ — a workspace owned by the caller, returned as ``me/`` lists it.

        Whether the caller may create one is asked before the body is read, so a
        refused caller hears that first, and asked again by ``create_owned_workspace``
        with the caller's row locked.
        """
        user = request.user
        try:
            ensure_workspace_create_allowed(user)
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            workspace = create_owned_workspace(
                user,
                name=data['name'],
                slug=data.get('slug', ''),
                region=data.get('region'),
                country=data.get('country', ''),
                currency=data.get('currency', ''),
                language=data.get('language', ''),
                current_workspace_id=_token_workspace_id(request),
            )
        except WorkspaceCreateForbidden as exc:
            return Response({'detail': exc.message, 'code': exc.code}, status=status.HTTP_403_FORBIDDEN)
        except WorkspaceLimitReached as exc:
            return Response(
                {'detail': exc.message, 'code': exc.code, 'limit': exc.limit},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except WorkspaceAlreadyExists as exc:
            # A slug that was free when the body was validated can be taken by the time it is written.
            return Response({'slug': [exc.message]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(get_user_workspace(user, workspace), status=status.HTTP_201_CREATED)

    # ── Custom actions ───────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        """GET /api/v1/platform/workspaces/me/ — current user's workspaces and whether they may create one."""
        return Response({
            'workspaces': get_user_workspaces(request.user),
            'is_platform_admin': is_platform_admin(request.user),
            'workspace_limit': max_owned_workspaces(),
            # Asked without a lock: what a create request would meet right now.
            'create_blocked': workspace_create_blocked(request.user),
        })

    # Suspending takes a workspace offline for its staff and its customers alike,
    # and resuming undoes a suspension whoever made it, so neither is a workspace
    # staff action: the viewset-wide IsAuthenticated would let any staff role in.
    @action(detail=True, methods=['post'], permission_classes=[IsPlatformAdmin])
    def suspend(self, request, pk=None):
        """POST /api/v1/platform/workspaces/{id}/suspend/ — platform admins only."""
        workspace = self.get_object()
        suspend_workspace(
            workspace,
            initiated_by=request.user,
            reason=request.data.get('reason', ''),
        )
        return Response({'status': 'suspended'})

    @action(detail=True, methods=['post'], permission_classes=[IsPlatformAdmin])
    def resume(self, request, pk=None):
        """POST /api/v1/platform/workspaces/{id}/resume/ — platform admins only."""
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

    # Read-only exemption: this is how a workspace pays, and paying is what ends
    # read-only mode. Refusing it would leave a lapsed workspace with no way out.
    @exempt_from_read_only
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
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by('price')
        if is_embedded_mode():
            # Every workspace keeps the plans it sells to its own customers in
            # the same table; the platform's pricing is only the management
            # Workspace's plans.
            platform_ws = get_platform_workspace()
            if platform_ws is None:
                return plans.none()
            plans = plans.filter(workspace=platform_ws)
        return plans


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

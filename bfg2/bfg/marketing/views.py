"""
BFG Promo Module API Views

ViewSets for promo module
"""

from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound
from decimal import Decimal

from bfg.core.permissions import IsWorkspaceStaff, IsWorkspaceAdmin
from bfg.marketing.models import Campaign, CampaignDisplay, CampaignParticipation, Coupon, ReferralProgram, DiscountRule, StampRecord
from bfg.marketing.models import GiftCard
from bfg.marketing.serializers import (
    CampaignSerializer,
    CampaignDisplaySerializer,
    CampaignParticipationSerializer,
    CouponSerializer,
    GiftCardSerializer,
    ReferralProgramSerializer,
    DiscountRuleSerializer,
    StampRecordSerializer,
)
from bfg.marketing.services.promo_service import CampaignService, StampService


def get_workspace(request):
    """Safely get workspace from request"""
    workspace = getattr(request, 'workspace', None)
    if not workspace:
        raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
    return workspace


class CampaignViewSet(viewsets.ModelViewSet):
    """Campaign management ViewSet"""
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get campaigns for current workspace"""
        workspace = get_workspace(self.request)
        return Campaign.objects.filter(
            workspace=workspace
        ).select_related('group', 'created_by').order_by('-start_date')
    
    def perform_create(self, serializer):
        """Create campaign with workspace"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace, created_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='join')
    def join(self, request, pk=None):
        """Register current user's customer in campaign (Boost). Optionally issue coupon from campaign.config."""
        campaign = self.get_object()
        workspace = get_workspace(request)
        customer = getattr(request, 'customer', None)
        if not customer:
            return Response(
                {'detail': 'Customer context required to join campaign.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        svc = CampaignService(workspace=workspace, user=request.user)
        try:
            participation, coupon = svc.join_campaign(customer, campaign)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'participation': CampaignParticipationSerializer(participation).data,
            'coupon': CouponSerializer(coupon).data if coupon else None,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='participations')
    def participations(self, request, pk=None):
        """List participations for this campaign."""
        campaign = self.get_object()
        qs = campaign.participations.select_related('customer').order_by('-created_at')
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = CampaignParticipationSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = CampaignParticipationSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='stamp-progress')
    def stamp_progress(self, request, pk=None):
        """Get stamp/redeem progress for current customer and this campaign."""
        campaign = self.get_object()
        customer = getattr(request, 'customer', None)
        if not customer:
            return Response(
                {'detail': 'Customer context required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace = get_workspace(request)
        progress = StampService(workspace=workspace, user=request.user).get_stamp_progress(customer, campaign)
        return Response(progress)

    @action(detail=True, methods=['post'], url_path='redeem')
    def redeem(self, request, pk=None):
        """Redeem stamp/redeem reward if eligible."""
        campaign = self.get_object()
        customer = getattr(request, 'customer', None)
        if not customer:
            return Response(
                {'detail': 'Customer context required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace = get_workspace(request)
        svc = StampService(workspace=workspace, user=request.user)
        try:
            redemption_record, coupon, gift_card = svc.redeem(customer, campaign)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'redemption': StampRecordSerializer(redemption_record).data,
            'coupon': CouponSerializer(coupon).data if coupon else None,
            'gift_card': None,
        }, status=status.HTTP_201_CREATED)


class CouponViewSet(viewsets.ModelViewSet):
    """Coupon management ViewSet"""
    serializer_class = CouponSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get coupons for current workspace"""
        workspace = get_workspace(self.request)
        queryset = Coupon.objects.filter(
            workspace=workspace
        ).select_related('campaign', 'discount_rule').order_by('-created_at')
        
        # Filter by active status if provided
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset
    
    def perform_create(self, serializer):
        """Create coupon with workspace"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)


class GiftCardViewSet(viewsets.ModelViewSet):
    """Gift card management ViewSet"""
    serializer_class = GiftCardSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get gift cards for current workspace"""
        queryset = GiftCard.objects.filter(
            workspace=self.request.workspace
        ).select_related('currency', 'customer')
        
        # Filter by active status if provided
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        # Filter by customer if provided
        customer_id = self.request.query_params.get('customer')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create gift card with workspace"""
        serializer.save(workspace=self.request.workspace)
    
    @action(detail=True, methods=['post'])
    def redeem(self, request, pk=None):
        """Redeem gift card"""
        gift_card = self.get_object()
        
        if not gift_card.is_active:
            return Response(
                {'detail': 'Gift card is not active'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(request.data.get('amount', 0))
        except (ValueError, TypeError):
            return Response(
                {'detail': 'Invalid amount'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if amount <= 0:
            return Response(
                {'detail': 'Amount must be greater than 0'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if gift_card.balance < amount:
            return Response(
                {'detail': f'Insufficient balance. Available: {gift_card.balance}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Redeem amount
        gift_card.balance -= amount
        gift_card.save()
        
        serializer = self.get_serializer(gift_card)
        return Response({
            'success': True,
            'redeemed_amount': str(amount),
            'remaining_balance': str(gift_card.balance),
            'gift_card': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate gift card"""
        gift_card = self.get_object()
        
        if not gift_card.is_active:
            return Response(
                {'detail': 'Gift card is already inactive'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        gift_card.is_active = False
        gift_card.save()
        
        serializer = self.get_serializer(gift_card)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate gift card"""
        gift_card = self.get_object()
        
        if gift_card.is_active:
            return Response(
                {'detail': 'Gift card is already active'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        gift_card.is_active = True
        gift_card.save()
        
        serializer = self.get_serializer(gift_card)
        return Response(serializer.data)


class ReferralProgramViewSet(viewsets.ModelViewSet):
    """Referral program management ViewSet"""
    serializer_class = ReferralProgramSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get referral programs for current workspace"""
        workspace = get_workspace(self.request)
        return ReferralProgram.objects.filter(
            workspace=workspace
        ).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create referral program with workspace"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)

class DiscountRuleViewSet(viewsets.ModelViewSet):
    """Discount rule management ViewSet"""
    serializer_class = DiscountRuleSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        """Get discount rules for current workspace"""
        workspace = get_workspace(self.request)
        return DiscountRule.objects.filter(
            workspace=workspace
        ).order_by('-created_at')

    def perform_create(self, serializer):
        """Create discount rule with workspace"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)


class CampaignParticipationViewSet(viewsets.ReadOnlyModelViewSet):
    """Campaign participation (Boost) list/detail - staff only."""
    serializer_class = CampaignParticipationSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        return CampaignParticipation.objects.filter(
            workspace=workspace
        ).select_related('campaign', 'customer').order_by('-created_at')


def _strip_non_file_image(data):
    """Remove image from data when it is not an uploaded file (e.g. edit without new image sends URL string)."""
    if data is None:
        return data
    data = data.copy()
    if 'image' not in data:
        return data
    img = data.get('image')
    if img is None or (isinstance(img, str) and not img.startswith('data:')):
        data.pop('image', None)
    elif not getattr(img, 'read', None):
        data.pop('image', None)
    return data


class CampaignDisplayViewSet(viewsets.ModelViewSet):
    """Campaign display (slides, featured categories/posts) CRUD. Campaign optional."""
    serializer_class = CampaignDisplaySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_serializer(self, *args, **kwargs):
        if 'data' in kwargs and kwargs['data'] is not None:
            kwargs['data'] = _strip_non_file_image(kwargs['data'])
        return super().get_serializer(*args, **kwargs)

    def get_queryset(self):
        workspace = get_workspace(self.request)
        return CampaignDisplay.objects.filter(
            Q(campaign__workspace=workspace) | Q(workspace=workspace)
        ).select_related('campaign', 'post').order_by('campaign', 'order', 'id')

    def perform_create(self, serializer):
        workspace = get_workspace(self.request)
        campaign = serializer.validated_data.get('campaign')
        if campaign:
            if campaign.workspace_id != workspace.id:
                raise NotFound("Campaign not in workspace.")
        else:
            serializer.validated_data['workspace'] = workspace
        serializer.save()


class StampRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """Stamp record list/detail - staff only."""
    serializer_class = StampRecordSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        return StampRecord.objects.filter(
            workspace=workspace
        ).select_related('campaign', 'customer', 'order').order_by('-created_at')

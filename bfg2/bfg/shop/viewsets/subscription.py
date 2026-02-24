"""
Subscription ViewSet
"""
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from bfg.core.permissions import IsWorkspaceAdmin
from bfg.shop.models import SubscriptionPlan
from bfg.shop.serializers import SubscriptionPlanSerializer


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    """Subscription plan management ViewSet (Admin only)"""
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        """Get subscription plans for current workspace"""
        return SubscriptionPlan.objects.filter(
            workspace=self.request.workspace
        ).prefetch_related('subscriptions')
    
    def perform_create(self, serializer):
        """Create subscription plan with workspace"""
        serializer.save(workspace=self.request.workspace)

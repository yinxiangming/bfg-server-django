"""
Subscription ViewSet
"""
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from bfg.core.permissions import StaffReadAdminWrite
from bfg.shop.models import SubscriptionPlan
from bfg.shop.serializers import SubscriptionPlanSerializer


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    """Subscription plan management ViewSet. Reads: any staff. Writes: admin only."""
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated, StaffReadAdminWrite]
    
    def get_queryset(self):
        """Get subscription plans for current workspace"""
        return SubscriptionPlan.objects.filter(
            workspace=self.request.workspace
        ).prefetch_related('subscriptions')
    
    def perform_create(self, serializer):
        """Create subscription plan with workspace"""
        serializer.save(workspace=self.request.workspace)

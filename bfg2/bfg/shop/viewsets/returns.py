"""
Returns ViewSets
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import datetime

from bfg.common.models import Customer
from bfg.shop.models import Return, ReturnLineItem
from bfg.shop.serializers import ReturnSerializer, ReturnLineItemSerializer


class ReturnViewSet(viewsets.ModelViewSet):
    """Return request management ViewSet"""
    serializer_class = ReturnSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get return requests"""
        workspace = self.request.workspace
        user = self.request.user
        
        queryset = Return.objects.filter(
            workspace=workspace
        ).select_related('order', 'customer').prefetch_related('items')
        
        if getattr(self.request, 'is_staff_member', False):
            status_filter = self.request.query_params.get('status')
            if status_filter:
                queryset = queryset.filter(status=status_filter)
        else:
            customer = Customer.objects.filter(
                workspace=workspace,
                user=user
            ).first()
            
            if customer:
                queryset = queryset.filter(customer=customer)
            else:
                return Return.objects.none()
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create return request"""
        customer = Customer.objects.get(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        return_number = f"RET-{datetime.date.today().strftime('%Y%m%d')}-{Return.objects.filter(workspace=self.request.workspace).count() + 1:04d}"
        
        serializer.save(
            workspace=self.request.workspace,
            customer=customer,
            return_number=return_number,
            status='open'
        )
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve return request (staff only)"""
        if not getattr(request, 'is_staff_member', False):
            return Response(
                {'detail': 'Only staff can approve returns'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return_request = self.get_object()
        
        if return_request.status != 'open':
            return Response(
                {'detail': 'Only open returns can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return_request.status = 'approved'
        return_request.approved_at = timezone.now()
        return_request.admin_note = request.data.get('admin_note', '')
        return_request.save()
        
        serializer = self.get_serializer(return_request)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject return request (staff only)"""
        if not getattr(request, 'is_staff_member', False):
            return Response(
                {'detail': 'Only staff can reject returns'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return_request = self.get_object()
        
        if return_request.status != 'open':
            return Response(
                {'detail': 'Only open returns can be rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return_request.status = 'rejected'
        return_request.admin_note = request.data.get('admin_note', '')
        return_request.save()
        
        serializer = self.get_serializer(return_request)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def process_refund(self, request, pk=None):
        """Process refund for approved return (staff only)"""
        if not getattr(request, 'is_staff_member', False):
            return Response(
                {'detail': 'Only staff can process refunds'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return_request = self.get_object()
        
        if return_request.status != 'approved':
            return Response(
                {'detail': 'Only approved returns can be refunded'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return_request.status = 'refunded'
        return_request.refunded_at = timezone.now()
        return_request.save()
        
        serializer = self.get_serializer(return_request)
        return Response(serializer.data)


class ReturnLineItemViewSet(viewsets.ModelViewSet):
    """Return line item management ViewSet"""
    serializer_class = ReturnLineItemSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get return line items"""
        queryset = ReturnLineItem.objects.filter(
            return_request__workspace=self.request.workspace
        ).select_related('return_request', 'order_item')
        
        return_id = self.request.query_params.get('return')
        if return_id:
            queryset = queryset.filter(return_request_id=return_id)
        
        return queryset


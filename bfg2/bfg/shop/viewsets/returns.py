"""
Returns ViewSets
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.utils import timezone
import datetime

from bfg.common.models import Customer
from bfg.shop.models import Return, ReturnLineItem
from bfg.shop.serializers import ReturnSerializer, ReturnLineItemSerializer


# What a customer may change on their own return request. Its status, the order
# it is against and the shop's note are staff decisions.
CUSTOMER_EDITABLE_RETURN_FIELDS = frozenset({'reason_category', 'customer_note'})


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
        
        order_id = self.request.query_params.get('order')
        if order_id:
            if not order_id.isdigit():
                raise ValidationError({'order': 'Expected an order id.'})
            queryset = queryset.filter(order_id=order_id)

        return queryset.order_by('-created_at')
    
    # Status -> the field recording when a return first reached it.
    STATUS_TIMESTAMP_FIELDS = {'approved': 'approved_at', 'refunded': 'refunded_at', 'closed': 'closed_at'}

    @staticmethod
    def _next_return_number(workspace):
        """Next return number not yet used in this workspace"""
        prefix = f"RET-{datetime.date.today().strftime('%Y%m%d')}-"
        sequence = Return.objects.filter(workspace=workspace).count() + 1
        # A deleted return shrinks the count, so the next number may already be taken.
        while Return.objects.filter(workspace=workspace, return_number=f"{prefix}{sequence:04d}").exists():
            sequence += 1
        return f"{prefix}{sequence:04d}"

    def perform_create(self, serializer):
        """Create return request"""
        workspace = self.request.workspace
        order = serializer.validated_data.get('order')
        if not order or order.workspace_id != workspace.id:
            raise ValidationError({'order': 'Invalid order.'})

        shop_fields = {}
        if getattr(self.request, 'is_staff_member', False):
            customer = order.customer
        else:
            customer = Customer.objects.get(
                workspace=workspace,
                user=self.request.user
            )
            if order.customer_id != customer.id:
                raise ValidationError({'order': 'You can only create returns for your own orders.'})
            # A customer opens the request; how it ends is recorded by staff.
            shop_fields = {'admin_note': '', 'closed_at': None}
        
        return_number = self._next_return_number(workspace)
        
        serializer.save(
            workspace=workspace,
            customer=customer,
            return_number=return_number,
            status='open',
            created_by=self.request.user,
            **shop_fields,
        )

    def perform_update(self, serializer):
        """Update return request (customers: their own note and reason, while open)"""
        if getattr(self.request, 'is_staff_member', False):
            order = serializer.validated_data.get('order')
            if order is not None and order.workspace_id != self.request.workspace.id:
                raise ValidationError({'order': 'Invalid order.'})
            stamped = {}
            field = self.STATUS_TIMESTAMP_FIELDS.get(serializer.validated_data.get('status'))
            if field and getattr(serializer.instance, field) is None and field not in serializer.validated_data:
                stamped[field] = timezone.now()
            serializer.save(**stamped)
            return

        restricted = sorted(set(serializer.validated_data) - CUSTOMER_EDITABLE_RETURN_FIELDS)
        if restricted:
            raise PermissionDenied(f"Only staff can change {', '.join(restricted)}.")
        if serializer.instance.status != 'open':
            raise ValidationError({'detail': 'This return has been reviewed and can no longer be changed.'})
        serializer.save()

    def perform_destroy(self, instance):
        """Delete return request (staff only)"""
        if not getattr(self.request, 'is_staff_member', False):
            raise PermissionDenied('Only staff can delete returns.')
        instance.delete()
    
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

        if not getattr(self.request, 'is_staff_member', False):
            queryset = queryset.filter(return_request__customer__user=self.request.user)
        
        return_id = self.request.query_params.get('return')
        if return_id:
            queryset = queryset.filter(return_request_id=return_id)
        
        return queryset

    def _writable_return(self, return_id):
        """Return request a line may be written against, as this caller"""
        is_staff = getattr(self.request, 'is_staff_member', False)
        returns = Return.objects.filter(workspace=self.request.workspace)
        if not is_staff:
            returns = returns.filter(customer__user=self.request.user)

        return_request = returns.filter(pk=return_id).first() if return_id is not None else None
        if return_request is None:
            raise ValidationError({'return_request': 'Invalid return.'})
        if not is_staff and return_request.status != 'open':
            raise ValidationError({'return_request': 'This return has been reviewed and can no longer be changed.'})
        return return_request

    @staticmethod
    def _validate_line(return_request, order_item, quantity, line=None):
        """A line returns part of the returned order, and never more than was ordered"""
        if order_item.order_id != return_request.order_id:
            raise ValidationError({'order_item': 'This item is not part of the returned order.'})
        if quantity < 1:
            raise ValidationError({'quantity': 'Return at least one unit.'})

        already_returned = ReturnLineItem.objects.filter(
            return_request=return_request, order_item=order_item
        ).exclude(pk=getattr(line, 'pk', None)).aggregate(total=Sum('quantity'))['total'] or 0
        if already_returned + quantity > order_item.quantity:
            raise ValidationError({'quantity': 'This is more than was ordered.'})

    def perform_create(self, serializer):
        """Create return line item"""
        data = serializer.validated_data
        return_request = self._writable_return(data.get('return_request'))
        self._validate_line(return_request, data['order_item'], data['quantity'])

        shop_fields = {}
        if not getattr(self.request, 'is_staff_member', False):
            # What happens to returned stock is decided when staff process the return.
            shop_fields = {'restock_action': 'no_restock'}
        serializer.save(return_request=return_request, **shop_fields)

    def perform_update(self, serializer):
        """Update return line item"""
        line = serializer.instance
        data = serializer.validated_data
        if data.get('return_request', line.return_request_id) != line.return_request_id:
            raise ValidationError({'return_request': 'A line cannot be moved to another return.'})
        return_request = self._writable_return(line.return_request_id)
        if 'restock_action' in data and not getattr(self.request, 'is_staff_member', False):
            raise PermissionDenied('Only staff can change restock_action.')

        self._validate_line(
            return_request,
            data.get('order_item', line.order_item),
            data.get('quantity', line.quantity),
            line=line,
        )
        serializer.save(return_request=return_request)

    def perform_destroy(self, instance):
        """Delete return line item"""
        self._writable_return(instance.return_request_id)
        instance.delete()


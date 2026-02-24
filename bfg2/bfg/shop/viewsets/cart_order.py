"""
Cart and Order ViewSets
"""
from datetime import timedelta

from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import PermissionDenied
from decimal import Decimal

from bfg.common.models import Customer, Address
from bfg.shop.models import Cart, CartItem, Order, OrderItem, Product, ProductVariant, Store
from bfg.delivery.models import PackageTemplate
from bfg.delivery.models import Package
from bfg.shop.serializers import (
    CartSerializer, OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer,
    OrderPackageSerializer, OrderPackageCreateSerializer
)
from bfg.shop.services import CartService, OrderService


class CartViewSet(viewsets.ModelViewSet):
    """
    Shopping cart ViewSet
    
    Supports both authenticated and anonymous (guest) users
    Anonymous carts are tracked by session_key, merged on login
    """
    serializer_class = CartSerializer
    http_method_names = ['get', 'post', 'delete']
    
    def get_permissions(self):
        """Allow anonymous access for cart operations"""
        return [AllowAny()]
    
    def get_queryset(self):
        """Get cart for current user"""
        user = self.request.user
        workspace = self.request.workspace
        
        if user.is_authenticated:
            customer, _ = Customer.objects.get_or_create(
                user=user,
                workspace=workspace,
                defaults={'is_active': True}
            )
            return Cart.objects.filter(workspace=workspace, customer=customer).prefetch_related('items__product', 'items__variant')
        else:
            session_key = self.request.session.session_key
            if session_key:
                return Cart.objects.filter(workspace=workspace, session_key=session_key, customer__isnull=True).prefetch_related('items__product', 'items__variant')
            return Cart.objects.none()
    
    def perform_create(self, serializer):
        """Create cart with workspace and customer/session"""
        user = self.request.user
        workspace = self.request.workspace
        
        if user.is_authenticated:
            customer, _ = Customer.objects.get_or_create(
                user=user,
                workspace=workspace,
                defaults={'is_active': True}
            )
            serializer.save(workspace=workspace, customer=customer)
        else:
            if not self.request.session.session_key:
                self.request.session.create()
            serializer.save(workspace=workspace, session_key=self.request.session.session_key)
    
    def _get_or_create_cart(self):
        """Helper to get or create cart for current user/session"""
        service = CartService(
            workspace=self.request.workspace,
            user=self.request.user if self.request.user.is_authenticated else None
        )
        
        if self.request.user.is_authenticated:
            customer, _ = Customer.objects.get_or_create(
                workspace=self.request.workspace,
                user=self.request.user,
                defaults={'is_active': True}
            )
            
            session_key = self.request.session.session_key
            if session_key:
                cart = service.merge_guest_cart_to_customer(session_key, customer)
            else:
                cart = service.get_or_create_cart(customer)
        else:
            if not self.request.session.session_key:
                self.request.session.create()
            
            session_key = self.request.session.session_key
            cart = service.get_or_create_guest_cart(session_key)
        
        return cart
    
    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get or create current user's cart (works for both auth and anonymous)"""
        cart = self._get_or_create_cart()
        serializer = self.get_serializer(cart)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def add_item(self, request):
        """Add item to current user's cart"""
        cart = self._get_or_create_cart()
        
        service = CartService(
            workspace=request.workspace,
            user=request.user if request.user.is_authenticated else None
        )
        
        product_id = request.data.get('product')
        variant_id = request.data.get('variant')
        quantity = request.data.get('quantity', 1)
        
        # Validate quantity
        try:
            quantity = int(quantity)
            if quantity <= 0:
                return Response(
                    {'detail': 'Quantity must be greater than 0'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if quantity > 10000:
                return Response(
                    {'detail': 'Quantity cannot exceed 10000'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {'detail': 'Quantity must be a valid integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not product_id:
            return Response(
                {'detail': 'Product is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            product = Product.objects.get(id=product_id, workspace=request.workspace)
            variant = ProductVariant.objects.get(id=variant_id) if variant_id else None
            
            service.add_to_cart(cart, product, quantity, variant)
            
            serializer = self.get_serializer(cart)
            return Response(serializer.data)
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except ProductVariant.DoesNotExist:
            return Response(
                {'detail': 'Product variant not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=False, methods=['post'])
    def update_item(self, request):
        """Update cart item quantity"""
        cart = self._get_or_create_cart()
        
        service = CartService(
            workspace=request.workspace,
            user=request.user if request.user.is_authenticated else None
        )
        
        item_id = request.data.get('item_id')
        quantity = request.data.get('quantity')
        
        if not item_id or quantity is None:
            return Response(
                {'detail': 'item_id and quantity are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate quantity
        try:
            quantity = int(quantity)
            if quantity <= 0:
                return Response(
                    {'detail': 'Quantity must be greater than 0'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if quantity > 10000:
                return Response(
                    {'detail': 'Quantity cannot exceed 10000'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (ValueError, TypeError):
            return Response(
                {'detail': 'Quantity must be a valid integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            cart_item = CartItem.objects.get(id=item_id, cart=cart)
            service.update_cart_item_quantity(cart_item, quantity)
            
            serializer = self.get_serializer(cart)
            return Response(serializer.data)
        except CartItem.DoesNotExist:
            return Response(
                {'detail': 'Cart item not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=False, methods=['post'])
    def remove_item(self, request):
        """Remove item from cart"""
        cart = self._get_or_create_cart()
        
        service = CartService(
            workspace=request.workspace,
            user=request.user if request.user.is_authenticated else None
        )
        
        item_id = request.data.get('item_id')
        if not item_id:
            return Response(
                {'detail': 'item_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            cart_item = CartItem.objects.get(id=item_id, cart=cart)
            service.remove_from_cart(cart_item)
            
            serializer = self.get_serializer(cart)
            return Response(serializer.data)
        except CartItem.DoesNotExist:
            return Response(
                {'detail': 'Cart item not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=False, methods=['post'])
    def clear(self, request):
        """Clear cart"""
        cart = self._get_or_create_cart()
        
        service = CartService(
            workspace=request.workspace,
            user=request.user if request.user.is_authenticated else None
        )
        
        service.clear_cart(cart)
        
        serializer = self.get_serializer(cart)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def checkout(self, request):
        """Checkout - requires authentication"""
        if not request.user.is_authenticated:
            return Response(
                {
                    'detail': 'Please login or register to complete checkout',
                    'login_required': True
                },
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        cart = self._get_or_create_cart()
        
        if not cart.items.exists():
            return Response(
                {'detail': 'Cart is empty'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        store_id = request.data.get('store')
        shipping_address_id = request.data.get('shipping_address')
        billing_address_id = request.data.get('billing_address')
        coupon_code = request.data.get('coupon_code')
        gift_card_code = request.data.get('gift_card_code')
        
        if not store_id or not shipping_address_id:
            return Response(
                {'detail': 'store and shipping_address are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            store = Store.objects.get(id=store_id, workspace=request.workspace)
            shipping_address = Address.objects.get(id=shipping_address_id)
            billing_address = None
            
            if billing_address_id:
                billing_address = Address.objects.get(id=billing_address_id)
            
            order_service = OrderService(
                workspace=request.workspace,
                user=request.user
            )
            
            order = order_service.create_order_from_cart(
                cart=cart,
                store=store,
                shipping_address=shipping_address,
                billing_address=billing_address,
                customer_note=request.data.get('customer_note', ''),
                coupon_code=coupon_code,
                gift_card_code=gift_card_code,
                user=request.user
            )
            
            from bfg.shop.serializers import OrderDetailSerializer
            serializer = OrderDetailSerializer(order, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Store.DoesNotExist:
            return Response(
                {'detail': 'Store not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Address.DoesNotExist:
            return Response(
                {'detail': 'Address not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class OrderViewSet(viewsets.ModelViewSet):
    """
    Order management ViewSet
    
    Customers can only see their own orders, staff can see all
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch']
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'create':
            return OrderCreateSerializer
        if self.action == 'retrieve' or self.action == 'update_items':
            return OrderDetailSerializer
        return OrderListSerializer
    
    def get_queryset(self):
        """Get orders based on permissions"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from bfg.common.models import Workspace
            workspace = Workspace.objects.filter(is_active=True).first()
            if not workspace:
                from rest_framework.exceptions import NotFound
                raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
            self.request.workspace = workspace
        
        user = self.request.user
        
        queryset = Order.objects.filter(workspace=workspace).select_related(
            'customer', 'customer__user', 'store', 'shipping_address', 'billing_address'
        ).prefetch_related(
            'items', 'items__product', 'items__variant',
            'invoices', 'invoices__items', 'invoices__currency',
            'payments', 'payments__gateway', 'payments__currency'
        )
        
        if not user.is_authenticated:
            return queryset.order_by('-created_at')
        
        from bfg.common.models import StaffMember
        is_staff = user.is_superuser or StaffMember.objects.filter(
            workspace=workspace,
            user=user,
            is_active=True
        ).exists()
        
        if is_staff:
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
                return Order.objects.none()
        
        return queryset.order_by('-created_at')

    @action(detail=False, methods=['get'], url_path='dashboard-stats')
    def dashboard_stats(self, request):
        """Return dashboard stats for admin: orders_today, revenue_today, customers_count, orders_last_7_days. Staff only."""
        from bfg.common.models import StaffMember
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            from bfg.common.models import Workspace
            workspace = Workspace.objects.filter(is_active=True).first()
            if not workspace:
                from rest_framework.exceptions import NotFound
                raise NotFound("No workspace available.")
            request.workspace = workspace
        is_staff = request.user.is_superuser or StaffMember.objects.filter(
            workspace=workspace, user=request.user, is_active=True
        ).exists()
        if not is_staff:
            raise PermissionDenied("Staff only.")
        today = timezone.now().date()
        orders_today = Order.objects.filter(workspace=workspace, created_at__date=today).count()
        rev = Order.objects.filter(
            workspace=workspace, created_at__date=today, payment_status='paid'
        ).aggregate(s=Sum('total'))['s']
        revenue_today = float(rev) if rev is not None else 0
        customers_count = Customer.objects.filter(workspace=workspace).count()
        start = today - timedelta(days=6)
        qs = (
            Order.objects.filter(workspace=workspace, created_at__date__gte=start)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        day_counts = {row['day'].isoformat() if row['day'] else None: row['count'] for row in qs}
        orders_last_7_days = []
        labels = []
        for i in range(7):
            d = start + timedelta(days=i)
            labels.append(d.strftime('%a'))
            orders_last_7_days.append(day_counts.get(d.isoformat(), 0))
        return Response({
            'orders_today': orders_today,
            'revenue_today': revenue_today,
            'customers_count': customers_count,
            'orders_last_7_days': orders_last_7_days,
            'categories': labels,
        })
    
    def perform_create(self, serializer):
        """Create order directly or from cart"""
        from bfg.common.services import AuditService
        
        # Only staff can create orders directly via API
        # Regular users must use cart checkout
        user = self.request.user
        workspace = self.request.workspace
        
        from bfg.common.models import StaffMember
        is_staff = user.is_superuser or StaffMember.objects.filter(
            workspace=workspace,
            user=user,
            is_active=True
        ).exists()
        
        if not is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only staff members can create orders directly. Please use cart checkout.")
        
        # Get customer
        customer_id = serializer.validated_data.get('customer_id')
        if not customer_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'customer_id': 'This field is required for direct order creation.'})
        
        from bfg.common.models import Customer
        customer = Customer.objects.get(
            id=customer_id,
            workspace=self.request.workspace
        )
        
        # Get store
        store_id = serializer.validated_data.pop('store_id')
        from bfg.shop.models import Store
        store = Store.objects.get(
            id=store_id,
            workspace=self.request.workspace
        )
        
        # Get or create shipping address
        shipping_address_id = serializer.validated_data.pop('shipping_address_id', None)
        if not shipping_address_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'shipping_address_id': 'This field is required.'})
        from bfg.common.models import Address
        shipping_address = Address.objects.get(
            id=shipping_address_id,
            workspace=self.request.workspace
        )
        
        # Get billing address (optional, defaults to shipping)
        billing_address_id = serializer.validated_data.pop('billing_address_id', None)
        billing_address = shipping_address
        if billing_address_id:
            billing_address = Address.objects.get(
                id=billing_address_id,
                workspace=self.request.workspace
            )
        
        # Get additional fields from serializer
        status = serializer.validated_data.get('status', 'pending')
        payment_status = serializer.validated_data.get('payment_status', 'pending')
        customer_note = serializer.validated_data.get('customer_note', '')
        admin_note = serializer.validated_data.get('admin_note', '')
        
        # Create order using service
        service = OrderService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        # Note: All financial fields (subtotal, shipping_cost, tax, discount, total) 
        # are now read_only and will be calculated by the service
        # For direct order creation, we start with empty order (no items yet)
        order = service.create_order(
            customer=customer,
            store=store,
            shipping_address=shipping_address,
            billing_address=billing_address,
            status=status,
            payment_status=payment_status,
            customer_note=customer_note,
            admin_note=admin_note,
        )
        
        serializer.instance = order
        
        # Audit log for staff-created orders
        audit = AuditService(workspace=self.request.workspace, user=self.request.user)
        description = f"Created order #{order.id} for {customer} - Total: {order.total}"
        audit.log_create(
            order,
            description=description,
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')
        )
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update order status (staff only)"""
        if not getattr(request, 'is_staff_member', False):
            return Response(
                {'detail': 'Only staff can update order status'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        order = self.get_object()
        new_status = request.data.get('status')
        
        if not new_status:
            return Response(
                {'detail': 'Status is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service = OrderService(
            workspace=request.workspace,
            user=request.user
        )
        
        order = service.update_order_status(order, new_status)
        serializer = self.get_serializer(order)
        return Response(serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """Update order (supports address updates)"""
        from bfg.common.models import Address
        from bfg.common.services import AuditService
        from rest_framework.exceptions import ValidationError
        
        order = self.get_object()
        
        # Save old address info before any updates
        old_shipping_address = order.shipping_address
        old_billing_address = order.billing_address
        old_shipping_address_id = order.shipping_address_id
        old_billing_address_id = order.billing_address_id
        
        # Check permissions - only staff can update orders
        from bfg.common.models import StaffMember
        is_staff = request.user.is_superuser or StaffMember.objects.filter(
            workspace=request.workspace,
            user=request.user,
            is_active=True
        ).exists()
        
        if not is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only staff members can update orders.")
        
        # Handle address updates (support both shipping_address and shipping_address_id)
        shipping_address_id = request.data.get('shipping_address') or request.data.get('shipping_address_id')
        billing_address_id = request.data.get('billing_address') or request.data.get('billing_address_id')
        
        changes = {}
        new_shipping_address = None
        new_billing_address = None
        
        if shipping_address_id is not None:
            try:
                shipping_address_id = int(shipping_address_id)
                new_shipping_address = Address.objects.get(
                    id=shipping_address_id,
                    workspace=request.workspace
                )
                # Check if address actually changed
                if old_shipping_address_id != shipping_address_id:
                    # Format old address street info
                    old_street = None
                    if old_shipping_address:
                        old_street_parts = [
                            old_shipping_address.address_line1,
                            old_shipping_address.address_line2
                        ]
                        old_street = ', '.join(filter(None, old_street_parts)) or None
                    
                    # Format new address street info
                    new_street_parts = [
                        new_shipping_address.address_line1,
                        new_shipping_address.address_line2
                    ]
                    new_street = ', '.join(filter(None, new_street_parts)) or None
                    
                    changes['shipping_address'] = {
                        'old': {
                            'id': old_shipping_address_id,
                            'street': old_street,
                            'full_name': old_shipping_address.full_name if old_shipping_address else None
                        },
                        'new': {
                            'id': shipping_address_id,
                            'street': new_street,
                            'full_name': new_shipping_address.full_name
                        }
                    }
            except (Address.DoesNotExist, ValueError):
                raise ValidationError({'shipping_address': 'Address not found'})
        
        if billing_address_id is not None:
            try:
                billing_address_id = int(billing_address_id)
                new_billing_address = Address.objects.get(
                    id=billing_address_id,
                    workspace=request.workspace
                )
                # Check if address actually changed
                if old_billing_address_id != billing_address_id:
                    # Format old address street info
                    old_street = None
                    if old_billing_address:
                        old_street_parts = [
                            old_billing_address.address_line1,
                            old_billing_address.address_line2
                        ]
                        old_street = ', '.join(filter(None, old_street_parts)) or None
                    
                    # Format new address street info
                    new_street_parts = [
                        new_billing_address.address_line1,
                        new_billing_address.address_line2
                    ]
                    new_street = ', '.join(filter(None, new_street_parts)) or None
                    
                    changes['billing_address'] = {
                        'old': {
                            'id': old_billing_address_id,
                            'street': old_street,
                            'full_name': old_billing_address.full_name if old_billing_address else None
                        },
                        'new': {
                            'id': billing_address_id,
                            'street': new_street,
                            'full_name': new_billing_address.full_name
                        }
                    }
            except (Address.DoesNotExist, ValueError):
                raise ValidationError({'billing_address': 'Address not found'})
        
        # Update address fields if changed
        if new_shipping_address and old_shipping_address_id != new_shipping_address.id:
            order.shipping_address = new_shipping_address
        if new_billing_address and old_billing_address_id != new_billing_address.id:
            order.billing_address = new_billing_address
        
        # Update other fields using serializer
        serializer = self.get_serializer(order, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Refresh to get updated data
        order.refresh_from_db()
        
        # Create audit log if addresses were changed
        if changes:
            audit = AuditService(workspace=request.workspace, user=request.user)
            address_changes = []
            
            # Build detailed description with street information
            descriptions = []
            if 'shipping_address' in changes:
                change = changes['shipping_address']
                old_street = change['old'].get('street', 'N/A')
                new_street = change['new'].get('street', 'N/A')
                descriptions.append(f"Shipping address: {old_street} → {new_street}")
                address_changes.append('shipping address')
            
            if 'billing_address' in changes:
                change = changes['billing_address']
                old_street = change['old'].get('street', 'N/A')
                new_street = change['new'].get('street', 'N/A')
                descriptions.append(f"Billing address: {old_street} → {new_street}")
                address_changes.append('billing address')
            
            description = f"Updated {', '.join(address_changes)} for order #{order.order_number}. " + " | ".join(descriptions)
            audit.log_update(
                order,
                changes=changes,
                description=description,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel order"""
        order = self.get_object()
        reason = request.data.get('reason', '')
        
        service = OrderService(
            workspace=request.workspace,
            user=request.user
        )
        
        order = service.cancel_order(order, reason)
        serializer = self.get_serializer(order)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def update_items(self, request, pk=None):
        """Update order items"""
        from decimal import Decimal
        from django.db import transaction
        
        order = self.get_object()
        items_data = request.data.get('items', [])
        
        if not items_data:
            return Response(
                {'detail': 'Items are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # Delete existing items
            order.items.all().delete()
            
            # Create new items
            subtotal = Decimal('0.00')
            
            for item_data in items_data:
                product_id = item_data.get('product')
                variant_id = item_data.get('variant')
                
                # Validate and get quantity
                try:
                    quantity = int(item_data.get('quantity', 1))
                    if quantity <= 0:
                        continue  # Skip invalid items
                    if quantity > 10000:
                        continue  # Skip items with excessive quantity
                except (ValueError, TypeError):
                    continue  # Skip items with invalid quantity
                
                # Security: Price must come from product/variant, not from user input
                # User can only specify quantity, not price
                if not product_id:
                    continue
                
                try:
                    product = Product.objects.get(id=product_id, workspace=request.workspace)
                    variant = None
                    if variant_id:
                        variant = ProductVariant.objects.get(id=variant_id, product=product)
                    
                    # Security: Use price from product/variant, not from user input
                    if variant:
                        price = variant.price
                    else:
                        price = product.price
                    
                    # Validate price is non-negative
                    if price < 0:
                        continue  # Skip items with negative price
                    
                    item_subtotal = price * quantity
                    subtotal += item_subtotal
                    
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        variant=variant,
                        product_name=product.name,
                        variant_name=variant.name if variant else '',
                        sku=variant.sku if variant else product.sku,
                        quantity=quantity,
                        price=price,  # From product/variant, not user input
                        subtotal=item_subtotal
                    )
                except (Product.DoesNotExist, ProductVariant.DoesNotExist):
                    continue
            
            # Update order totals
            shipping_cost = order.shipping_cost or Decimal('0.00')
            tax = order.tax or Decimal('0.00')
            discount = order.discount or Decimal('0.00')
            order.subtotal = subtotal
            order.total = subtotal + shipping_cost + tax - discount
            order.save()
        
        # Refresh from database to ensure all related objects are loaded
        order.refresh_from_db()
        
        serializer = self.get_serializer(order)
        return Response(serializer.data)


class OrderPackageViewSet(viewsets.ModelViewSet):
    """
    Order package management ViewSet (Staff only)
    Manages actual packages used for fulfilling orders.
    Uses bfg.delivery.Package model with order relation.
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'delete']
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'create':
            return OrderPackageCreateSerializer
        return OrderPackageSerializer
    
    def get_queryset(self):
        """Get packages for order"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return Package.objects.none()
        
        # Only get packages that are linked to orders (not consignments)
        queryset = Package.objects.filter(
            order__workspace=workspace,
            order__isnull=False
        ).select_related('template', 'order')
        
        # Filter by order if specified
        order_id = self.request.query_params.get('order')
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        
        return queryset.order_by('-created_at')
    
    def create(self, request, *args, **kwargs):
        """Create package for order and return full detail"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # Return full detail using OrderPackageSerializer
        instance = serializer.instance
        instance.refresh_from_db()
        detail_serializer = OrderPackageSerializer(instance, context={'request': request})
        headers = self.get_success_headers(detail_serializer.data)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def perform_create(self, serializer):
        """Create package for order"""
        import random
        import string
        from django.utils import timezone
        from bfg.delivery.models import FreightStatus, FreightState
        from bfg.common.services import AuditService
        
        order_id = self.request.data.get('order')
        if not order_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'order': 'This field is required.'})
        
        order = Order.objects.get(
            id=order_id,
            workspace=self.request.workspace
        )
        
        # Generate package number if not provided
        package_number = self.request.data.get('package_number')
        if not package_number:
            date_str = timezone.now().strftime('%Y%m%d')
            random_str = ''.join(random.choices(string.digits, k=4))
            package_number = f"PKG-{date_str}-{random_str}"
        
        # Get default status
        status_obj = FreightStatus.objects.filter(
            workspace=self.request.workspace,
            state=FreightState.PENDING.value
        ).first()
        
        if not status_obj:
            # Create a default status if none exists
            status_obj, _ = FreightStatus.objects.get_or_create(
                workspace=self.request.workspace,
                code='pending',
                defaults={
                    'name': 'Pending',
                    'state': FreightState.PENDING.value,
                    'order': 0
                }
            )
        
        package = serializer.save(
            order=order,
            package_number=package_number,
            state=FreightState.PENDING.value,
            status=status_obj
        )
        
        # Audit log
        audit = AuditService(workspace=self.request.workspace, user=self.request.user)
        description = f"Created package {package_number} for order {order.order_number}"
        audit.log_create(
            package,
            description=description,
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')
        )

        # Emit event for decoupled order status sync (e.g. first package -> processing)
        from bfg.core.events import global_dispatcher
        global_dispatcher.dispatch('order.package.added', {
            'workspace': self.request.workspace,
            'user': self.request.user,
            'data': {'order': order, 'package': package}
        })
    
    def destroy(self, request, *args, **kwargs):
        """Delete package with audit log"""
        from bfg.common.services import AuditService
        
        package = self.get_object()
        package_number = package.package_number
        order_number = package.order.order_number if package.order else 'N/A'
        
        # Audit log before deletion
        audit = AuditService(workspace=request.workspace, user=request.user)
        description = f"Deleted package {package_number} from order {order_number}"
        audit.log_delete(
            package,
            description=description,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return super().destroy(request, *args, **kwargs)
    
    @action(detail=False, methods=['post'])
    def calculate_shipping(self, request):
        """
        Calculate shipping cost based on packages for an order
        Uses FreightService configuration
        """
        order_id = request.data.get('order')
        freight_service_id = request.data.get('freight_service_id')
        
        if not order_id:
            return Response(
                {'detail': 'order is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            order = Order.objects.get(
                id=order_id,
                workspace=request.workspace
            )
        except Order.DoesNotExist:
            return Response(
                {'detail': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all packages for the order
        packages = order.packages.all()
        
        if not packages.exists():
            return Response({
                'total_packages': 0,
                'total_actual_weight': '0.00',
                'total_volumetric_weight': '0.00',
                'total_billing_weight': '0.00',
                'shipping_cost': '0.00',
                'message': 'No packages found for this order'
            })
        
        # Calculate totals
        total_actual_weight = Decimal('0')
        total_volumetric_weight = Decimal('0')
        total_billing_weight = Decimal('0')
        
        for pkg in packages:
            pieces = pkg.pieces or 1
            actual_weight = pkg.weight or Decimal('0')
            total_actual_weight += actual_weight * pieces
            total_volumetric_weight += pkg.volumetric_weight * pieces
            total_billing_weight += pkg.total_billing_weight
        
        # Calculate shipping cost using FreightService
        shipping_cost = Decimal('0')
        freight_service_name = None
        
        if freight_service_id:
            try:
                from bfg.delivery.models import FreightService
                freight_service = FreightService.objects.get(
                    id=freight_service_id,
                    workspace=request.workspace,
                    is_active=True
                )
                freight_service_name = freight_service.name
                
                config = freight_service.config or {}
                if config:
                    try:
                        from bfg.delivery.services.freight_calculator import calculate_shipping_cost
                        from bfg.shop.services.freight_price_resolver import get_freight_price_value
                        context = None
                        if config.get('mode') == 'conditional':
                            context = {
                                'freight': {
                                    'weight': total_billing_weight,
                                    'order_amount': getattr(order, 'subtotal', None) or getattr(order, 'total', None) or Decimal('0'),
                                },
                                'weight': total_billing_weight,
                            }
                        get_price = get_freight_price_value(request.workspace)
                        shipping_cost = calculate_shipping_cost(
                            total_billing_weight, config, context=context, get_price_value=get_price
                        )
                    except (ImportError, ValueError, RuntimeError):
                        base = freight_service.base_price or Decimal('0')
                        per_kg = freight_service.price_per_kg or Decimal('0')
                        shipping_cost = base + (total_billing_weight * per_kg)
                else:
                    # Simple formula if no config
                    base = freight_service.base_price or Decimal('0')
                    per_kg = freight_service.price_per_kg or Decimal('0')
                    shipping_cost = base + (total_billing_weight * per_kg)
                    
            except FreightService.DoesNotExist:
                pass
        
        return Response({
            'total_packages': packages.count(),
            'total_actual_weight': str(total_actual_weight.quantize(Decimal('0.01'))),
            'total_volumetric_weight': str(total_volumetric_weight.quantize(Decimal('0.01'))),
            'total_billing_weight': str(total_billing_weight.quantize(Decimal('0.01'))),
            'shipping_cost': str(shipping_cost.quantize(Decimal('0.01'))),
            'freight_service': freight_service_name,
        })
    
    @action(detail=False, methods=['post'])
    def update_order_shipping(self, request):
        """
        Update order's shipping cost based on packages
        Uses FreightService configuration
        """
        order_id = request.data.get('order')
        freight_service_id = request.data.get('freight_service_id')
        
        if not order_id:
            return Response(
                {'detail': 'order is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not freight_service_id:
            return Response(
                {'detail': 'freight_service_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            order = Order.objects.get(
                id=order_id,
                workspace=request.workspace
            )
        except Order.DoesNotExist:
            return Response(
                {'detail': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Calculate shipping cost
        packages = order.packages.all()
        total_billing_weight = sum(pkg.total_billing_weight for pkg in packages)
        
        try:
            from bfg.delivery.models import FreightService
            freight_service = FreightService.objects.get(
                id=freight_service_id,
                workspace=request.workspace,
                is_active=True
            )
            
            config = freight_service.config or {}
            if config:
                try:
                    from bfg.delivery.services.freight_calculator import calculate_shipping_cost
                    from bfg.shop.services.freight_price_resolver import get_freight_price_value
                    context = None
                    if config.get('mode') == 'conditional':
                        context = {
                            'freight': {
                                'weight': total_billing_weight,
                                'order_amount': order.subtotal or order.total or Decimal('0'),
                            },
                            'weight': total_billing_weight,
                        }
                    get_price = get_freight_price_value(request.workspace)
                    shipping_cost = calculate_shipping_cost(
                        total_billing_weight, config, context=context, get_price_value=get_price
                    )
                except (ImportError, ValueError, RuntimeError):
                    base = freight_service.base_price or Decimal('0')
                    per_kg = freight_service.price_per_kg or Decimal('0')
                    shipping_cost = base + (total_billing_weight * per_kg)
            else:
                base = freight_service.base_price or Decimal('0')
                per_kg = freight_service.price_per_kg or Decimal('0')
                shipping_cost = base + (total_billing_weight * per_kg)
                
        except FreightService.DoesNotExist:
            return Response(
                {'detail': 'FreightService not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Update order
        order.shipping_cost = shipping_cost
        order.total = order.subtotal + order.shipping_cost + order.tax - order.discount
        order.save()
        
        return Response({
            'order_id': order.id,
            'shipping_cost': str(order.shipping_cost),
            'total': str(order.total),
            'freight_service': freight_service.name,
            'billing_weight': str(total_billing_weight.quantize(Decimal('0.01')))
        })


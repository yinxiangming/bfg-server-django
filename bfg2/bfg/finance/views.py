"""
BFG Finance Module API Views

ViewSets for finance module
"""

from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff, CanManagePayments, CanManageInvoices
from bfg.finance.models import (
    Currency, PaymentGateway, PaymentMethod, Brand, FinancialCode,
    Invoice, Payment, Refund, TaxRate, Transaction
)
from bfg.finance.serializers import (
    CurrencySerializer, PaymentGatewaySerializer, PaymentMethodSerializer,
    BrandSerializer, FinancialCodeSerializer,
    InvoiceListSerializer, InvoiceDetailSerializer, InvoiceCreateSerializer,
    PaymentSerializer, RefundSerializer, TaxRateSerializer,
    TransactionSerializer
)
from bfg.finance.services import PaymentService, InvoiceService, TaxService


class CurrencyViewSet(viewsets.ModelViewSet):
    """Currency ViewSet (Read-only)"""
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]
    queryset = Currency.objects.filter(is_active=True)


class BrandViewSet(viewsets.ModelViewSet):
    """Brand ViewSet"""
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get brands for current workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        
        return Brand.objects.filter(workspace=workspace).select_related('address').order_by('-is_default', 'name')
    
    def perform_create(self, serializer):
        """Create brand with workspace"""
        serializer.save(workspace=self.request.workspace)


class FinancialCodeViewSet(viewsets.ModelViewSet):
    """Financial Code ViewSet"""
    serializer_class = FinancialCodeSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_workspace(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        return workspace

    def get_queryset(self):
        """Get financial codes for current workspace"""
        workspace = self.get_workspace()
        queryset = FinancialCode.objects.filter(workspace=workspace)
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            is_active_bool = is_active.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(is_active=is_active_bool)
        else:
            queryset = queryset.filter(is_active=True)
        return queryset.order_by('code')

    def create(self, request, *args, **kwargs):
        """Create financial code; return 409 on duplicate (workspace, code)."""
        from django.db import IntegrityError
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return Response(
                {"detail": "No workspace. Send X-Workspace-ID header."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError:
            return Response(
                {"detail": "A financial code with this code already exists for this workspace."},
                status=status.HTTP_409_CONFLICT
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """Create financial code with workspace"""
        serializer.save(workspace=self.request.workspace)


class PaymentGatewayViewSet(viewsets.ModelViewSet):
    """Payment gateway ViewSet (Admin only)"""
    serializer_class = PaymentGatewaySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        return PaymentGateway.objects.filter(workspace=self.request.workspace)
    
    def perform_create(self, serializer):
        """Create payment gateway with workspace"""
        serializer.save(workspace=self.request.workspace)
    
    @action(detail=False, methods=['get'])
    def plugins(self, request):
        """
        List available payment gateway plugins (from gateways/ directory).
        Returns list with gateway_type, display_name, config_schema, supported_methods.
        """
        from bfg.finance.gateways.loader import GatewayLoader
        plugins = []
        for gateway_type, _ in GatewayLoader.list_available_plugins().items():
            plugin_info = GatewayLoader.get_plugin_info(gateway_type)
            if plugin_info:
                plugins.append(plugin_info)
        return Response(plugins)


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """Payment method ViewSet"""
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get payment methods for current workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        
        queryset = PaymentMethod.objects.filter(
            customer__workspace=workspace
        ).select_related('customer', 'gateway')
        
        # Filter by customer if provided
        customer_id = self.request.query_params.get('customer')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        
        return queryset.order_by('-is_default', '-created_at')
    
    def perform_create(self, serializer):
        """Create payment method with customer"""
        from bfg.common.models import Customer
        from bfg.common.models import Address
        
        customer_id = serializer.validated_data.get('customer_id')
        if not customer_id:
            raise serializers.ValidationError({'customer_id': 'This field is required.'})
        
        customer = Customer.objects.get(
            id=customer_id,
            workspace=self.request.workspace
        )
        
        # Get billing address if provided
        billing_address = None
        billing_address_id = serializer.validated_data.pop('billing_address_id', None)
        if billing_address_id:
            billing_address = Address.objects.filter(
                id=billing_address_id,
                workspace=self.request.workspace
            ).first()
            if not billing_address:
                raise serializers.ValidationError({
                    'billing_address_id': f'Address with id {billing_address_id} not found.'
                })
        
        # Ensure only one default payment method per customer
        if serializer.validated_data.get('is_default'):
            PaymentMethod.objects.filter(
                customer=customer,
                is_default=True
            ).update(is_default=False)
        
        # Set workspace from request
        serializer.save(
            customer=customer,
            workspace=self.request.workspace,
            billing_address=billing_address
        )
    
    def perform_update(self, serializer):
        """Update payment method"""
        from bfg.common.models import Address
        
        # Get billing address if provided
        billing_address_id = serializer.validated_data.pop('billing_address_id', None)
        if billing_address_id is not None:
            if billing_address_id:
                billing_address = Address.objects.filter(
                    id=billing_address_id,
                    workspace=self.request.workspace
                ).first()
                if not billing_address:
                    raise serializers.ValidationError({
                        'billing_address_id': f'Address with id {billing_address_id} not found.'
                    })
            else:
                billing_address = None
            serializer.validated_data['billing_address'] = billing_address
        
        # Ensure only one default payment method per customer
        if serializer.validated_data.get('is_default'):
            PaymentMethod.objects.filter(
                customer=serializer.instance.customer,
                is_default=True
            ).exclude(pk=serializer.instance.pk).update(is_default=False)
        
        serializer.save()


class InvoiceViewSet(viewsets.ModelViewSet):
    """Invoice ViewSet - Finance staff only can modify"""
    permission_classes = [IsAuthenticated, CanManageInvoices]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceCreateSerializer
        if self.action in ['retrieve', 'update', 'partial_update', 'update_items']:
            return InvoiceDetailSerializer
        return InvoiceListSerializer
    
    def create(self, request, *args, **kwargs):
        """Create invoice and return full detail with items"""
        from bfg.common.services import AuditService
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = serializer.save()
        
        # Refresh from database to ensure all related objects (items) are loaded
        invoice.refresh_from_db()
        
        # Prefetch items for the serializer
        from django.db.models import Prefetch
        invoice = Invoice.objects.prefetch_related('items').get(pk=invoice.pk)
        
        # Audit log
        audit = AuditService(workspace=request.workspace, user=request.user)
        description = f"Created invoice {invoice.invoice_number} for {invoice.customer} - Total: {invoice.total} {invoice.currency.code}"
        audit.log_create(
            invoice,
            description=description,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        # Return full invoice detail with items using InvoiceDetailSerializer
        detail_serializer = InvoiceDetailSerializer(invoice, context={'request': request})
        headers = self.get_success_headers(detail_serializer.data)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def get_queryset(self):
        queryset = Invoice.objects.filter(
            workspace=self.request.workspace
        ).select_related('customer', 'currency', 'order', 'brand')
        
        # Filter by order if provided
        order_id = self.request.query_params.get('order')
        if order_id:
            try:
                queryset = queryset.filter(order_id=int(order_id))
            except (ValueError, TypeError):
                pass  # Ignore invalid order_id
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-issue_date')
    
    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Send invoice"""
        from bfg.common.services import AuditService
        
        invoice = self.get_object()
        service = InvoiceService(workspace=request.workspace, user=request.user)
        invoice = service.send_invoice(invoice)
        
        # Audit log
        audit = AuditService(workspace=request.workspace, user=request.user)
        description = f"Sent invoice {invoice.invoice_number} to {invoice.customer}"
        audit.log_action(
            'send',
            invoice,
            description=description,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        serializer = self.get_serializer(invoice)
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """Delete invoice with audit log"""
        from bfg.common.services import AuditService
        
        invoice = self.get_object()
        invoice_number = invoice.invoice_number
        customer_name = str(invoice.customer)
        
        # Audit log before deletion
        audit = AuditService(workspace=request.workspace, user=request.user)
        description = f"Deleted invoice {invoice_number} for {customer_name}"
        audit.log_delete(
            invoice,
            description=description,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        return super().destroy(request, *args, **kwargs)
    
    @action(detail=True, methods=['get'])
    def download_pdf(self, request, pk=None):
        """Download invoice as PDF"""
        invoice = self.get_object()
        service = InvoiceService(workspace=request.workspace, user=request.user)
        pdf_content = service.generate_pdf(invoice)
        
        response = HttpResponse(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
        return response
    
    @action(detail=True, methods=['post'])
    def update_items(self, request, pk=None):
        """Update invoice items"""
        from decimal import Decimal
        from django.db import transaction
        from bfg.finance.models import InvoiceItem
        
        invoice = self.get_object()
        items_data = request.data.get('items', [])
        
        if not items_data:
            return Response(
                {'detail': 'Items are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            # Delete existing items
            invoice.items.all().delete()
            
            # Create new items
            subtotal = Decimal('0.00')
            total_tax = Decimal('0.00')
            
            # Get workspace tax rate
            from bfg.finance.models import TaxRate
            try:
                tax_rate_obj = TaxRate.objects.filter(
                    workspace=invoice.workspace,
                    is_active=True
                ).first()
                # Rate is stored as percentage (e.g., 10 for 10%), convert to decimal
                workspace_tax_rate = (tax_rate_obj.rate / Decimal('100')) if tax_rate_obj else Decimal('0')
            except:
                workspace_tax_rate = Decimal('0')
            
            for item_data in items_data:
                description = item_data.get('description', '')
                
                if not description:
                    continue
                
                # Validate quantity
                try:
                    quantity = Decimal(str(item_data.get('quantity', 1)))
                    if quantity <= 0:
                        continue  # Skip invalid items
                    if quantity > 10000:
                        continue  # Skip items with excessive quantity
                except (ValueError, TypeError, Exception):
                    continue  # Skip items with invalid quantity
                
                # Security: unit_price should come from product if product_id is provided
                unit_price = Decimal(str(item_data.get('unit_price', 0)))
                
                # Validate unit_price
                if unit_price < 0:
                    continue  # Skip items with negative price
                if unit_price > 999999.99:
                    continue  # Skip items with excessive price
                
                # Validate discount (should be between 0 and 1)
                try:
                    discount = Decimal(str(item_data.get('discount', '1.00')))
                    if discount < 0:
                        discount = Decimal('0.00')  # Clamp to 0
                    if discount > 1:
                        discount = Decimal('1.00')  # Clamp to 1
                except (ValueError, TypeError, Exception):
                    discount = Decimal('1.00')  # Default to no discount
                
                tax_type = item_data.get('tax_type', 'default')
                financial_code_id = item_data.get('financial_code_id')
                product_id = item_data.get('product')
                
                # Security: If product_id is provided, use product price instead of user input
                if product_id:
                    try:
                        from bfg.shop.models import Product
                        product = Product.objects.get(id=product_id, workspace=invoice.workspace)
                        # Override unit_price with product price
                        unit_price = product.price
                    except Product.DoesNotExist:
                        pass  # Use provided unit_price if product not found
                
                # Calculate item subtotal with discount
                item_subtotal = unit_price * quantity * discount
                
                # Calculate tax based on tax_type
                if tax_type == 'no_tax':
                    item_tax = Decimal('0.00')
                elif tax_type == 'zero_gst':
                    item_tax = Decimal('0.00')
                else:  # 'default'
                    item_tax = item_subtotal * workspace_tax_rate
                
                print(f"Item: {description}, subtotal: {item_subtotal}, tax_type: {tax_type}, tax_rate: {workspace_tax_rate}, calculated_tax: {item_tax}")
                
                subtotal += item_subtotal
                total_tax += item_tax
                
                InvoiceItem.objects.create(
                    invoice=invoice,
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    subtotal=item_subtotal,
                    tax=item_tax,
                    tax_type=tax_type,
                    financial_code_id=financial_code_id if financial_code_id else None,
                    product_id=product_id if product_id else None
                )
            
            # Update invoice totals
            old_subtotal = invoice.subtotal
            old_tax = invoice.tax
            old_total = invoice.total
            
            invoice.subtotal = subtotal
            invoice.tax = total_tax
            invoice.total = subtotal + total_tax
            invoice.save()
        
        
        # Refresh from database to ensure all related objects are loaded
        invoice.refresh_from_db()
        
        # Audit log for item updates
        from bfg.common.services import AuditService
        audit = AuditService(workspace=request.workspace, user=request.user)
        changes = {
            'subtotal': {'old': str(old_subtotal), 'new': str(invoice.subtotal)},
            'tax': {'old': str(old_tax), 'new': str(invoice.tax)},
            'total': {'old': str(old_total), 'new': str(invoice.total)},
            'items_count': {'old': 0, 'new': invoice.items.count()}
        }
        audit.log_update(
            invoice,
            changes=changes,
            description=f"Updated invoice {invoice.invoice_number} items - New total: {invoice.total} {invoice.currency.code}",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        
        serializer = self.get_serializer(invoice)
        return Response(serializer.data)


class PaymentViewSet(viewsets.ModelViewSet):
    """Payment ViewSet
    
    Payment creation is restricted to Customer Service and Finance staff only.
    Other staff members can view but not create payments.
    """
    permission_classes = [IsAuthenticated, CanManagePayments]
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'create':
            from bfg.finance.serializers import PaymentCreateSerializer
            return PaymentCreateSerializer
        return PaymentSerializer

    
    def get_queryset(self):
        queryset = Payment.objects.filter(
            workspace=self.request.workspace
        ).select_related('customer', 'gateway', 'currency')
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create payment using service"""
        from bfg.common.models import Customer
        from bfg.finance.models import PaymentGateway, Currency
        from bfg.finance.services import PaymentService
        from bfg.shop.models import Order
        from bfg.finance.models import Invoice
        from bfg.common.services import AuditService
        
        # Get or create customer
        customer_id = serializer.validated_data.get('customer_id')
        if customer_id:
            customer = Customer.objects.get(id=customer_id, workspace=self.request.workspace)
        else:
            # Use current user's customer
            customer, _ = Customer.objects.get_or_create(
                user=self.request.user,
                workspace=self.request.workspace,
                defaults={'is_active': True}
            )
        
        # Get required objects
        gateway = PaymentGateway.objects.get(
            id=serializer.validated_data['gateway_id'],
            workspace=self.request.workspace
        )
        currency = Currency.objects.get(id=serializer.validated_data['currency_id'])
        
        # Get optional objects
        order = None
        if serializer.validated_data.get('order_id'):
            order = Order.objects.get(
                id=serializer.validated_data['order_id'],
                workspace=self.request.workspace
            )
        
        invoice = None
        if serializer.validated_data.get('invoice_id'):
            invoice = Invoice.objects.get(
                id=serializer.validated_data['invoice_id'],
                workspace=self.request.workspace
            )
        
        payment_method = None
        if serializer.validated_data.get('payment_method_id'):
            from bfg.finance.models import PaymentMethod
            payment_method = PaymentMethod.objects.get(
                id=serializer.validated_data['payment_method_id']
            )
        
        # Create payment using service
        service = PaymentService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        payment = service.create_payment(
            customer=customer,
            amount=serializer.validated_data['amount'],
            currency=currency,
            gateway=gateway,
            order=order,
            invoice=invoice,
            payment_method=payment_method,
        )
        
        serializer.instance = payment
        
        # Audit log
        audit = AuditService(workspace=self.request.workspace, user=self.request.user)
        description = f"Created payment of {payment.amount} {payment.currency.code}"
        if order:
            description += f" for Order #{order.id}"
        if invoice:
            description += f" for Invoice #{invoice.invoice_number}"
        
        audit.log_create(
            payment,
            description=description,
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')
        )
    
    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """Process payment"""
        payment = self.get_object()
        service = PaymentService(workspace=request.workspace, user=request.user)
        
        try:
            payment = service.process_payment(payment)
            serializer = self.get_serializer(payment)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def intent(self, request):
        """
        Create a Stripe PaymentIntent for an existing order payment (staff/admin flow).

        This endpoint is used when staff need to take payment using the customer's saved
        PaymentMethod from admin pages. The payment completion is still finalized via
        Stripe webhook (payment.completed event triggers email notification).
        """
        class PaymentIntentRequestSerializer(serializers.Serializer):
            order_id = serializers.IntegerField()
            gateway_id = serializers.IntegerField(required=False, allow_null=True)
            payment_method_id = serializers.IntegerField()
            customer_id = serializers.IntegerField(required=False, allow_null=True)
            save_card = serializers.BooleanField(required=False, default=False)

        req_serializer = PaymentIntentRequestSerializer(data=request.data)
        req_serializer.is_valid(raise_exception=True)

        order_id = req_serializer.validated_data['order_id']
        gateway_id = req_serializer.validated_data.get('gateway_id')
        payment_method_id = req_serializer.validated_data['payment_method_id']
        customer_id = req_serializer.validated_data.get('customer_id')
        save_card = req_serializer.validated_data.get('save_card', False)

        # Load order
        try:
            order = Order.objects.get(id=order_id, workspace=request.workspace)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        # Determine customer (default to order.customer for safety)
        customer = order.customer
        if customer_id and customer.id != customer_id:
            raise serializers.ValidationError({'customer_id': 'Customer does not match the order customer.'})

        # Select gateway
        if gateway_id:
            try:
                gateway = PaymentGateway.objects.get(id=gateway_id, workspace=request.workspace)
            except PaymentGateway.DoesNotExist:
                return Response({'detail': 'Payment gateway not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            gateway = PaymentGateway.objects.filter(workspace=request.workspace, is_active=True).first()
            if not gateway:
                return Response({'detail': 'No active payment gateway found'}, status=status.HTTP_400_BAD_REQUEST)

        # Currency (match storefront behavior)
        default_currency_code = 'USD'
        if hasattr(request.workspace, 'workspace_settings') and request.workspace.workspace_settings:
            default_currency_code = request.workspace.workspace_settings.default_currency or 'USD'
        try:
            currency = Currency.objects.get(code=default_currency_code, is_active=True)
        except Currency.DoesNotExist:
            currency = Currency.objects.filter(is_active=True).first()
            if not currency:
                return Response(
                    {'detail': 'No active currency found. Please configure a currency first.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Payment method must belong to this customer
        try:
            payment_method = PaymentMethod.objects.get(id=payment_method_id, customer=customer)
        except PaymentMethod.DoesNotExist:
            return Response({'detail': 'Payment method not found'}, status=status.HTTP_404_NOT_FOUND)

        # Reuse existing pending payment for this order when possible (keeps invoice linkage)
        payment = Payment.objects.filter(
            workspace=request.workspace,
            order=order,
            customer=customer,
            status='pending'
        ).first()

        if payment:
            updated_fields = []
            if payment.gateway_id != gateway.id:
                payment.gateway = gateway
                payment.set_gateway_snapshot(gateway)
                updated_fields.extend(["gateway", "gateway_display_name", "gateway_type"])
            if payment.payment_method_id != payment_method.id:
                payment.payment_method = payment_method
                updated_fields.append('payment_method')
            if updated_fields:
                payment.save(update_fields=updated_fields)
        else:
            # Attach invoice if one exists for this order
            invoice = Invoice.objects.filter(workspace=request.workspace, order=order).order_by('-created_at').first()
            service = PaymentService(workspace=request.workspace, user=request.user)
            payment = service.create_payment(
                customer=customer,
                amount=order.total,
                currency=currency,
                gateway=gateway,
                order=order,
                invoice=invoice,
                payment_method=payment_method
            )

        # Generate gateway payload via plugin system (returns client_secret)
        from bfg.finance.gateways.loader import get_gateway_plugin
        plugin = get_gateway_plugin(gateway)
        if not plugin:
            return Response({'detail': 'Payment gateway plugin not available'}, status=status.HTTP_400_BAD_REQUEST)

        gateway_token = payment_method.gateway_token if payment_method else None
        stripe_payment_method_id = gateway_token if gateway_token and gateway_token.startswith('pm_') else None

        payment_intent = plugin.create_payment_intent(
            customer=customer,
            amount=payment.amount,
            currency=payment.currency,
            payment_method_id=stripe_payment_method_id,
            order_id=order.id,
            metadata={
                'payment_id': str(payment.id),
                'payment_number': payment.payment_number,
            },
            save_card=save_card
        )

        payment_intent_id = payment_intent.get('payment_intent_id') or payment_intent.get('id')
        if payment_intent_id and payment.gateway_transaction_id != payment_intent_id:
            payment.gateway_transaction_id = payment_intent_id
            payment.save(update_fields=['gateway_transaction_id'])

        return Response(
            {
                'payment_id': payment.id,
                'payment_number': payment.payment_number,
                'amount': str(payment.amount),
                'currency': currency.code,
                'gateway_payload': payment_intent,
                'status': payment.status
            },
            status=status.HTTP_201_CREATED
        )


class RefundViewSet(viewsets.ModelViewSet):
    """Refund ViewSet (Staff only)"""
    serializer_class = RefundSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        return Refund.objects.filter(
            payment__workspace=self.request.workspace
        ).select_related(
            'payment__customer', 'payment__currency'
        ).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create refund using service for validation"""
        from bfg.finance.services import PaymentService
        from bfg.common.services import AuditService
        from decimal import Decimal
        
        payment = serializer.validated_data['payment']
        amount = Decimal(str(serializer.validated_data['amount']))
        reason = serializer.validated_data.get('reason', '')
        
        # Use service to create refund (validates amount doesn't exceed payment)
        service = PaymentService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        try:
            refund = service.create_refund(
                payment=payment,
                amount=amount,
                reason=reason
            )
            serializer.instance = refund
            
            # Audit log
            audit = AuditService(workspace=self.request.workspace, user=self.request.user)
            description = f"Created refund of {refund.amount} {payment.currency.code} for Payment #{payment.id}"
            if reason:
                description += f" - Reason: {reason}"
            
            audit.log_create(
                refund,
                description=description,
                ip_address=self.request.META.get('REMOTE_ADDR'),
                user_agent=self.request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception as e:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': str(e)})


class TaxRateViewSet(viewsets.ModelViewSet):
    """Tax rate ViewSet (Admin only)"""
    serializer_class = TaxRateSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        return TaxRate.objects.filter(workspace=self.request.workspace)


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """Transaction ViewSet (Read-only)"""
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        return Transaction.objects.filter(
            workspace=self.request.workspace
        ).select_related('customer', 'currency').order_by('-created_at')

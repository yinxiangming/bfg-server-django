"""
BFG Finance Module Serializers

Serializers for finance module models
"""

from rest_framework import serializers
from bfg.finance.models import (
    Currency, PaymentGateway, PaymentMethod, Brand, FinancialCode,
    Invoice, InvoiceItem, Payment, Refund, TaxRate, Transaction
)


class CurrencySerializer(serializers.ModelSerializer):
    """Currency serializer"""
    
    class Meta:
        model = Currency
        fields = ['id', 'code', 'name', 'symbol', 'decimal_places', 'is_active']
        read_only_fields = ['id']


class PaymentGatewaySerializer(serializers.ModelSerializer):
    """Payment gateway serializer"""
    
    # Expose both config and test_config for editing
    config = serializers.JSONField(required=False, allow_null=True)
    test_config = serializers.JSONField(required=False, allow_null=True)
    supported_clients = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentGateway
        fields = [
            'id', 'name', 'gateway_type', 'config', 'test_config', 'is_active', 'is_test_mode',
            'supported_clients', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'supported_clients']
    
    def get_supported_clients(self, obj):
        """From plugin: empty list means all clients (web, android, ios, mp) supported."""
        from bfg.finance.gateways.loader import GatewayLoader
        info = GatewayLoader.get_plugin_info(obj.gateway_type)
        return (info or {}).get('supported_clients') or []
    
    def to_representation(self, instance):
        """Return both config and test_config when reading"""
        ret = super().to_representation(instance)
        # Ensure both fields are returned
        ret['config'] = instance.config or {}
        ret['test_config'] = instance.test_config or {}
        return ret
    
    def to_internal_value(self, data):
        """Parse JSON strings for config fields"""
        # Get the base data
        ret = super().to_internal_value(data)
        
        # Parse JSON strings if provided
        for field in ['config', 'test_config']:
            if field in data:
                field_data = data[field]
                if isinstance(field_data, str):
                    import json
                    try:
                        ret[field] = json.loads(field_data) if field_data.strip() else {}
                    except (json.JSONDecodeError, TypeError):
                        raise serializers.ValidationError({field: 'Invalid JSON format'})
        
        return ret
    
    def update(self, instance, validated_data):
        """Update instance, saving both config and test_config"""
        # Update other fields
        for attr, value in validated_data.items():
            if attr not in ['config', 'test_config']:
                setattr(instance, attr, value)
        
        # Save config and test_config if provided
        if 'config' in validated_data:
            instance.config = validated_data['config'] or {}
        if 'test_config' in validated_data:
            instance.test_config = validated_data['test_config'] or {}
        
        instance.save()
        return instance
    
    def create(self, validated_data):
        """Create instance, saving both config and test_config"""
        # Get config fields
        config_data = validated_data.pop('config', {}) or {}
        test_config_data = validated_data.pop('test_config', {}) or {}
        
        # Create instance
        instance = super().create(validated_data)
        
        # Set config fields
        instance.config = config_data
        instance.test_config = test_config_data
        instance.save()
        
        return instance


class BrandSerializer(serializers.ModelSerializer):
    """Brand serializer"""
    address = serializers.SerializerMethodField()
    
    class Meta:
        model = Brand
        fields = [
            'id', 'name', 'logo', 'address', 'is_default',
            'tax_id', 'registration_number', 'invoice_note',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_address(self, obj):
        """Return full address object if exists"""
        if obj.address:
            from bfg.common.serializers import AddressSerializer
            return AddressSerializer(obj.address).data
        return None


class FinancialCodeSerializer(serializers.ModelSerializer):
    """Financial code serializer"""
    
    class Meta:
        model = FinancialCode
        fields = [
            'id', 'code', 'name', 'description', 'unit_price', 'unit',
            'tax_type', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PaymentMethodSerializer(serializers.ModelSerializer):
    """
    Payment method serializer
    
    Security: gateway_token is read-only and should only be set by payment gateway integrations.
    Never expose or allow direct modification of sensitive payment data.
    
    For Stripe integration:
    - Pass stripe_payment_method_data in create request:
        {
            "gateway": <gateway_id>,
            "stripe_payment_method_data": {
                "type": "card",
                "card": {
                    "token": "tok_..."  # From Stripe Elements
                }
            },
            "is_default": true
        }
    """
    gateway_name = serializers.CharField(source='gateway.name', read_only=True)
    customer_id = serializers.IntegerField(write_only=True, required=False)
    billing_address_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    is_expired = serializers.BooleanField(read_only=True)
    expires_soon = serializers.BooleanField(read_only=True)
    # method_type is optional when using gateway_payment_method_data (plugin sets it)
    method_type = serializers.CharField(required=False)
    # Gateway-specific payment method data (e.g., Stripe PaymentMethod ID)
    # Format depends on gateway: Stripe uses {"payment_method_id": "pm_..."}
    gateway_payment_method_data = serializers.DictField(write_only=True, required=False)
    # Legacy support for Stripe
    stripe_payment_method_data = serializers.DictField(write_only=True, required=False)
    
    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'customer', 'customer_id', 'gateway', 'gateway_name', 'method_type',
            'gateway_token', 'cardholder_name', 'card_brand', 'card_last4',
            'card_exp_month', 'card_exp_year', 'expires_at',  # expires_at kept for backward compatibility
            'display_info', 'billing_address', 'billing_address_id',
            'is_default', 'is_active', 'is_expired', 'expires_soon',
            'gateway_payment_method_data', 'stripe_payment_method_data',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'customer', 'gateway_token', 'created_at', 'updated_at',
            'is_expired', 'expires_soon'
        ]
    
    def validate_card_exp_month(self, value):
        """Validate expiration month"""
        if value is not None and not (1 <= value <= 12):
            raise serializers.ValidationError("Expiration month must be between 1 and 12")
        return value
    
    def validate_card_exp_year(self, value):
        """Validate expiration year"""
        if value is not None:
            from django.utils import timezone
            current_year = timezone.now().year
            if value < current_year:
                raise serializers.ValidationError("Expiration year cannot be in the past")
            if value > current_year + 20:
                raise serializers.ValidationError("Expiration year is too far in the future")
        return value
    
    def validate_card_last4(self, value):
        """Validate last 4 digits"""
        if value:
            if not value.isdigit() or len(value) != 4:
                raise serializers.ValidationError("Last 4 digits must be exactly 4 numeric characters")
        return value
    
    def validate(self, attrs):
        """Cross-field validation"""
        # Ensure gateway_token is not directly set (should come from gateway integration)
        if 'gateway_token' in attrs:
            raise serializers.ValidationError({
                'gateway_token': 'Gateway token cannot be set directly. It must be provided by the payment gateway integration.'
            })
        
        return attrs


class InvoiceItemSerializer(serializers.ModelSerializer):
    """Invoice item serializer"""
    financial_code = FinancialCodeSerializer(read_only=True)
    financial_code_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True
    )
    
    # Security: Calculation fields must be read-only
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    tax = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = InvoiceItem
        fields = [
            'id', 'description', 'quantity', 'unit_price', 'discount',
            'subtotal', 'tax', 'tax_type', 'financial_code', 'financial_code_id', 'product'
        ]
        read_only_fields = ['id', 'subtotal', 'tax']
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        from decimal import Decimal
        if value is None:
            raise serializers.ValidationError("Quantity is required")
        if isinstance(value, (int, float, str)):
            value = Decimal(str(value))
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        if value > 10000:  # Reasonable upper limit
            raise serializers.ValidationError("Quantity cannot exceed 10000")
        return value
    
    def validate_unit_price(self, value):
        """Validate unit_price is non-negative"""
        from decimal import Decimal
        if value is None:
            raise serializers.ValidationError("Unit price is required")
        if isinstance(value, (int, float, str)):
            value = Decimal(str(value))
        if value < 0:
            raise serializers.ValidationError("Unit price cannot be negative")
        if value > 999999.99:  # Reasonable upper limit
            raise serializers.ValidationError("Unit price cannot exceed 999999.99")
        return value
    
    def validate_discount(self, value):
        """Validate discount is between 0 and 1 (as multiplier)"""
        from decimal import Decimal
        if value is None:
            return Decimal('1.00')  # Default no discount
        if isinstance(value, (int, float, str)):
            value = Decimal(str(value))
        if value < 0:
            raise serializers.ValidationError("Discount multiplier cannot be negative")
        if value > 1:
            raise serializers.ValidationError("Discount multiplier cannot exceed 1.00 (100%)")
        return value
    
    def validate_financial_code_id(self, value):
        """Validate financial_code_id exists and belongs to workspace"""
        if value is None:
            return value
        
        if self.context and 'request' in self.context:
            from bfg.finance.models import FinancialCode
            workspace = self.context['request'].workspace
            try:
                financial_code = FinancialCode.objects.get(
                    id=value,
                    workspace=workspace,
                    is_active=True
                )
                return financial_code.id
            except FinancialCode.DoesNotExist:
                raise serializers.ValidationError(f"Financial code {value} not found or not active in this workspace")
        
        return value
    
    def create(self, validated_data):
        """Handle financial_code_id conversion"""
        financial_code_id = validated_data.pop('financial_code_id', None)
        if financial_code_id:
            from bfg.finance.models import FinancialCode
            validated_data['financial_code'] = FinancialCode.objects.get(id=financial_code_id)
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Handle financial_code_id conversion"""
        financial_code_id = validated_data.pop('financial_code_id', None)
        if financial_code_id is not None:
            from bfg.finance.models import FinancialCode
            if financial_code_id:
                validated_data['financial_code'] = FinancialCode.objects.get(id=financial_code_id)
            else:
                validated_data['financial_code'] = None
        return super().update(instance, validated_data)


class InvoiceListSerializer(serializers.ModelSerializer):
    """Invoice list serializer (concise)"""
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    
    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'customer', 'customer_name',
            'brand', 'brand_name', 'status', 'total', 'currency', 'currency_code',
            'issue_date', 'due_date', 'paid_date', 'notes', 'created_at'
        ]
        read_only_fields = ['id', 'invoice_number', 'created_at']


class InvoiceCreateSerializer(serializers.ModelSerializer):
    """Invoice create serializer"""
    items = InvoiceItemSerializer(many=True, write_only=True)
    
    # Security: All calculation fields must be read-only, calculated from items
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    tax = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = Invoice
        fields = [
            'customer', 'order', 'subscription', 'brand', 'status',
            'subtotal', 'tax', 'total', 'currency',
            'issue_date', 'due_date', 'notes', 'items'
        ]
        read_only_fields = ['subtotal', 'tax', 'total']
        extra_kwargs = {
            'currency': {'required': False, 'allow_null': True},
            'brand': {'required': False, 'allow_null': True}
        }
    
    def create(self, validated_data):
        from decimal import Decimal
        from bfg.finance.models import InvoiceItem, Currency
        
        items_data = validated_data.pop('items', [])
        workspace = self.context['request'].workspace
        
        # Get or set default brand if not provided
        if 'brand' not in validated_data or not validated_data['brand']:
            # Try to get default brand for workspace
            try:
                default_brand = Brand.objects.get(workspace=workspace, is_default=True)
                validated_data['brand'] = default_brand
            except Brand.DoesNotExist:
                # No default brand, leave as None
                pass
        
        # Get or set default currency if not provided
        if 'currency' not in validated_data or not validated_data['currency']:
            # Try to get default currency from workspace settings
            default_currency_code = 'USD'  # Default fallback
            if hasattr(workspace, 'workspace_settings') and workspace.workspace_settings:
                default_currency_code = workspace.workspace_settings.default_currency or 'USD'
            
            # Get currency by code
            try:
                currency = Currency.objects.get(code=default_currency_code, is_active=True)
            except Currency.DoesNotExist:
                # Fallback to first active currency
                currency = Currency.objects.filter(is_active=True).first()
                if not currency:
                    raise serializers.ValidationError({'currency': 'No active currency found. Please create a currency first.'})
            
            validated_data['currency'] = currency
        
        # Get tax rate from workspace settings (default to 15% = 0.15)
        tax_rate = Decimal('0.15')  # Default NZ GST rate as decimal
        
        # Try to get from TaxRate model first
        try:
            from bfg.finance.models import TaxRate
            tax_rate_obj = TaxRate.objects.filter(
                workspace=workspace,
                is_active=True
            ).first()
            if tax_rate_obj:
                # Rate is stored as percentage (e.g., 10 for 10%), convert to decimal
                tax_rate = tax_rate_obj.rate / Decimal('100')
        except:
            # Fallback to workspace settings if TaxRate not available
            if hasattr(workspace, 'workspace_settings') and workspace.workspace_settings:
                if hasattr(workspace.workspace_settings, 'tax_rate') and workspace.workspace_settings.tax_rate:
                    # Assume workspace_settings.tax_rate is also stored as percentage
                    tax_rate = Decimal(str(workspace.workspace_settings.tax_rate)) / Decimal('100')
        
        # Calculate subtotal and tax from items
        subtotal = Decimal('0.00')
        total_tax = Decimal('0.00')
        
        for item in items_data:
            # Apply discount to item subtotal: unit_price × quantity × discount
            discount = item.get('discount', Decimal('1.00'))
            if isinstance(discount, (int, float, str)):
                discount = Decimal(str(discount))
            
            unit_price = Decimal(str(item['unit_price']))
            quantity = Decimal(str(item['quantity']))
            item_subtotal = unit_price * quantity * discount
            
            # Calculate tax for this item based on tax_type
            tax_type = item.get('tax_type', 'default')
            if tax_type == 'default':
                item_tax = item_subtotal * tax_rate
            else:  # 'no_tax' or 'zero_gst'
                item_tax = Decimal('0.00')
            
            subtotal += item_subtotal
            total_tax += item_tax
        
        # Use calculated values
        validated_data['subtotal'] = subtotal
        validated_data['tax'] = total_tax
        validated_data['total'] = subtotal + total_tax
        
        # Generate invoice number if not provided
        if 'invoice_number' not in validated_data:
            from bfg.finance.services import InvoiceService
            service = InvoiceService(
                workspace=workspace,
                user=self.context['request'].user
            )
            validated_data['invoice_number'] = service._generate_invoice_number()
        
        # Set workspace
        validated_data['workspace'] = workspace
        
        # Create invoice
        invoice = Invoice.objects.create(**validated_data)
        
        # Create invoice items
        for item_data in items_data:
            # Recalculate subtotal with discount for each item
            discount = item_data.get('discount', Decimal('1.00'))
            if isinstance(discount, (int, float, str)):
                discount = Decimal(str(discount))
            
            unit_price = Decimal(str(item_data['unit_price']))
            quantity = Decimal(str(item_data['quantity']))
            item_subtotal = unit_price * quantity * discount
            item_data['subtotal'] = item_subtotal
            
            # Calculate tax for this item
            tax_type = item_data.get('tax_type', 'default')
            if tax_type == 'default':
                item_tax = item_subtotal * tax_rate
            else:  # 'no_tax' or 'zero_gst'
                item_tax = Decimal('0.00')
            item_data['tax'] = item_tax
            
            # financial_code_id is already handled by InvoiceItemSerializer
            InvoiceItem.objects.create(
                invoice=invoice,
                **item_data
            )
        
        return invoice


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """Invoice detail serializer (full)"""
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    brand = BrandSerializer(read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)
    
    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'customer', 'customer_name',
            'order', 'subscription', 'brand', 'brand_name', 'status',
            'subtotal', 'tax', 'total', 'currency', 'currency_code',
            'issue_date', 'due_date', 'paid_date', 'notes',
            'items', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'invoice_number', 'created_at', 'updated_at']


class PaymentSerializer(serializers.ModelSerializer):
    """Payment serializer"""
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    gateway_name = serializers.SerializerMethodField()

    def get_gateway_name(self, obj):
        return obj.get_gateway_display_name()
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    order_id = serializers.IntegerField(source='order.id', read_only=True, allow_null=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True, allow_null=True)
    payment_method_display = serializers.SerializerMethodField()
    
    def get_payment_method_display(self, obj):
        """Get payment method display info"""
        if not obj.payment_method:
            return None
        
        # Use display_info if available
        if obj.payment_method.display_info:
            return obj.payment_method.display_info
        
        # Build display info from card brand and last4
        if obj.payment_method.method_type == 'card':
            brand = obj.payment_method.card_brand or 'Card'
            last4 = obj.payment_method.card_last4 or '****'
            # Capitalize first letter of brand
            brand_display = brand.capitalize() if brand != 'amex' else 'Amex'
            return f"{brand_display} •••• {last4}"
        elif obj.payment_method.method_type == 'bank':
            return 'Bank Account'
        elif obj.payment_method.method_type == 'wallet':
            return 'Digital Wallet'
        
        return None
    
    class Meta:
        model = Payment
        fields = [
            'id', 'payment_number', 'customer', 'customer_name',
            'invoice', 'order', 'order_id', 'order_number', 'gateway', 'gateway_name',
            'payment_method', 'payment_method_display', 'amount', 'currency', 'currency_code',
            'status', 'gateway_transaction_id',
            'created_at', 'completed_at'
        ]
        read_only_fields = [
            'id', 'payment_number', 'gateway_transaction_id',
            'created_at', 'completed_at'
        ]


class PaymentCreateSerializer(serializers.ModelSerializer):
    """Payment create serializer"""
    customer_id = serializers.IntegerField(write_only=True, required=False)
    gateway_id = serializers.IntegerField(write_only=True, required=True)
    currency_id = serializers.IntegerField(write_only=True, required=True)
    order_id = serializers.IntegerField(write_only=True, required=False)
    invoice_id = serializers.IntegerField(write_only=True, required=False)
    payment_method_id = serializers.IntegerField(write_only=True, required=False)
    
    # Read fields for response
    id = serializers.IntegerField(read_only=True)
    payment_number = serializers.CharField(read_only=True)
    customer = serializers.IntegerField(source='customer.id', read_only=True)
    gateway = serializers.IntegerField(source='gateway_id', read_only=True, allow_null=True)
    currency = serializers.IntegerField(source='currency.id', read_only=True)
    
    # Security: Amount should be read-only and calculated from order/invoice
    # For staff/admin manual payments, amount can be set but should be validated
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    
    class Meta:
        model = Payment
        fields = [
            'id', 'payment_number', 'customer', 'customer_id',
            'gateway', 'gateway_id', 'currency', 'currency_id',
            'order', 'order_id', 'invoice', 'invoice_id',
            'payment_method', 'payment_method_id',
            'amount', 'status', 'created_at'
        ]
        read_only_fields = ['id', 'payment_number', 'customer', 'gateway', 
                           'currency', 'created_at']
    
    def validate(self, data):
        """Validate payment data and ensure amount matches order/invoice"""
        from decimal import Decimal
        from bfg.shop.models import Order
        from bfg.finance.models import Invoice
        
        order_id = data.get('order_id')
        invoice_id = data.get('invoice_id')
        amount = data.get('amount')
        
        # If order is provided, amount should match order total
        if order_id:
            try:
                order = Order.objects.get(id=order_id, workspace=self.context['request'].workspace)
                if amount is None:
                    # Auto-set amount from order
                    data['amount'] = order.total
                    data['currency_id'] = order.store.currency.id if hasattr(order.store, 'currency') and order.store.currency else data.get('currency_id')
                elif Decimal(str(amount)) != order.total:
                    # Security: Warn if amount doesn't match, but allow staff to override
                    from bfg.common.models import StaffMember
                    is_staff = self.context['request'].user.is_superuser or StaffMember.objects.filter(
                        workspace=self.context['request'].workspace,
                        user=self.context['request'].user,
                        is_active=True
                    ).exists()
                    if not is_staff:
                        raise serializers.ValidationError({
                            'amount': f'Amount must match order total: {order.total}'
                        })
            except Order.DoesNotExist:
                raise serializers.ValidationError({'order_id': 'Order not found'})
        
        # If invoice is provided, amount should match invoice total
        if invoice_id:
            try:
                invoice = Invoice.objects.get(id=invoice_id, workspace=self.context['request'].workspace)
                if amount is None:
                    # Auto-set amount from invoice
                    data['amount'] = invoice.total
                    data['currency_id'] = invoice.currency.id if invoice.currency else data.get('currency_id')
                elif Decimal(str(amount)) != invoice.total:
                    # Security: Warn if amount doesn't match, but allow staff to override
                    from bfg.common.models import StaffMember
                    is_staff = self.context['request'].user.is_superuser or StaffMember.objects.filter(
                        workspace=self.context['request'].workspace,
                        user=self.context['request'].user,
                        is_active=True
                    ).exists()
                    if not is_staff:
                        raise serializers.ValidationError({
                            'amount': f'Amount must match invoice total: {invoice.total}'
                        })
            except Invoice.DoesNotExist:
                raise serializers.ValidationError({'invoice_id': 'Invoice not found'})
        
        # If neither order nor invoice, amount is required
        if not order_id and not invoice_id:
            if not amount or Decimal(str(amount)) <= 0:
                raise serializers.ValidationError({
                    'amount': 'Amount must be greater than 0 when no order/invoice is provided'
                })
        
        return data


class RefundSerializer(serializers.ModelSerializer):
    """Refund serializer"""
    payment_number = serializers.CharField(source='payment.payment_number', read_only=True)
    currency_code = serializers.CharField(source='payment.currency.code', read_only=True)
    
    class Meta:
        model = Refund
        fields = [
            'id', 'payment', 'payment_number', 'amount',
            'currency_code', 'reason', 'status',
            'gateway_refund_id', 'created_at', 'completed_at'
        ]
        read_only_fields = ['id', 'gateway_refund_id', 'created_at', 'completed_at']
    
    def validate(self, data):
        """Validate refund amount doesn't exceed payment amount"""
        from decimal import Decimal
        payment = data.get('payment')
        amount = data.get('amount')
        
        if payment and amount:
            # Check total refunded amount (exclude current instance if updating)
            existing_refunds = payment.refunds.all()
            if self.instance:
                existing_refunds = existing_refunds.exclude(id=self.instance.id)
            total_refunded = sum(refund.amount for refund in existing_refunds)
            
            if total_refunded + Decimal(str(amount)) > payment.amount:
                raise serializers.ValidationError({
                    'amount': f'Refund amount exceeds available amount. '
                             f'Payment: {payment.amount}, Already refunded: {total_refunded}, '
                             f'Available: {payment.amount - total_refunded}'
                })
        
        return data


class TaxRateSerializer(serializers.ModelSerializer):
    """Tax rate serializer"""
    
    class Meta:
        model = TaxRate
        fields = [
            'id', 'name', 'rate', 'country', 'state', 'is_active'
        ]
        read_only_fields = ['id']


class TransactionSerializer(serializers.ModelSerializer):
    """Transaction serializer"""
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_type', 'customer', 'customer_name',
            'amount', 'currency', 'currency_code',
            'payment', 'invoice', 'description', 'notes',
            'created_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_created_by_name(self, obj):
        """Get created_by user's full name or username"""
        if obj.created_by:
            if hasattr(obj.created_by, 'get_full_name') and obj.created_by.get_full_name():
                return obj.created_by.get_full_name()
            return obj.created_by.username
        return None
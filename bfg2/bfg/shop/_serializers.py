"""
BFG Shop Module Serializers

Serializers for shop module models
"""

from rest_framework import serializers
from decimal import Decimal
from pydantic import ValidationError as PydanticValidationError

from bfg.core.schema_convert import validation_error_to_message
from bfg.common.models import Media
from bfg.common.serializers import MediaLinkSerializer as BaseMediaLinkSerializer
from bfg.shop.models import (
    ProductCategory, ProductTag, Product, ProductVariant, VariantInventory,
    Cart, CartItem, Order, OrderItem, ProductReview, Store,
    SalesChannel, ProductChannelListing, ChannelCollection, Return, ReturnLineItem,
    SubscriptionPlan
)
from bfg.shop.schemas import (
    ProductCategoryRulesModel,
    prepare_category_rules_value,
)
from bfg.delivery.models import PackageTemplate
from bfg.delivery.models import Package


class ProductCategorySerializer(serializers.ModelSerializer):
    """Product category serializer"""
    children = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductCategory
        fields = [
            'id', 'name', 'slug', 'description', 'parent',
            'icon', 'image', 'order', 'is_active', 'language', 'children',
            'rules', 'rule_match_type'
        ]
        read_only_fields = ['id']
    
    def get_children(self, obj):
        """Get children categories recursively"""
        children = obj.children.filter(is_active=True).order_by('order', 'name')
        return ProductCategorySerializer(children, many=True).data

    def validate_rules(self, value):
        """Validate ProductCategory.rules JSON structure."""
        try:
            normalized = prepare_category_rules_value(value)
            ProductCategoryRulesModel.model_validate({'rules': normalized})
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        except PydanticValidationError as exc:
            raise serializers.ValidationError(validation_error_to_message(exc))
        return normalized


class ProductTagSerializer(serializers.ModelSerializer):
    """Product tag serializer"""
    
    class Meta:
        model = ProductTag
        fields = ['id', 'name', 'slug', 'language']
        read_only_fields = ['id']


class MediaSerializer(serializers.ModelSerializer):
    """Independent Media serializer"""
    file = serializers.SerializerMethodField()
    
    class Meta:
        model = Media
        fields = ['id', 'workspace', 'file', 'external_url', 'media_type', 'alt_text', 'width', 'height', 'uploaded_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file(self, obj):
        """Get full file URL"""
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None


# Note: ProductMediaSerializer has been removed, use MediaLinkSerializer from bfg.common.serializers instead
# For Product-specific serialization, use BaseMediaLinkSerializer or create a custom serializer


class ProductVariantSerializer(serializers.ModelSerializer):
    """Product variant serializer"""
    available = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'product', 'sku', 'name', 'options', 'price', 'compare_price',
            'stock_quantity', 'available', 'weight', 'is_active', 'order'
        ]
        read_only_fields = ['id']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set queryset for product field dynamically
        if self.context.get('request'):
            request = self.context['request']
            if hasattr(request, 'workspace'):
                from bfg.shop.models import Product
                self.fields['product'] = serializers.PrimaryKeyRelatedField(
                    queryset=Product.objects.filter(workspace=request.workspace),
                    required=True
                )
    
    def get_available(self, obj):
        """Get available quantity"""
        return obj.stock_quantity > 0
    
    def validate_price(self, value):
        """Validate price is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Price cannot be negative")
            if value > 999999.99:
                raise serializers.ValidationError("Price cannot exceed 999999.99")
        return value
    
    def validate_compare_price(self, value):
        """Validate compare_price is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Compare price cannot be negative")
        return value
    
    def validate_stock_quantity(self, value):
        """Validate stock_quantity is non-negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Stock quantity cannot be negative")
        return value


class VariantInventorySerializer(serializers.ModelSerializer):
    """Variant inventory serializer"""
    variant_name = serializers.CharField(source='variant.name', read_only=True)
    variant_sku = serializers.CharField(source='variant.sku', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    
    class Meta:
        model = VariantInventory
        fields = [
            'id', 'variant', 'variant_name', 'variant_sku',
            'warehouse', 'warehouse_name', 'quantity', 'reserved', 'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']
    
    def validate_quantity(self, value):
        """Validate quantity is non-negative"""
        if value < 0:
            raise serializers.ValidationError("Quantity cannot be negative")
        return value
    
    def validate_reserved(self, value):
        """Validate reserved is non-negative"""
        if value < 0:
            raise serializers.ValidationError("Reserved quantity cannot be negative")
        return value


class ProductListSerializer(serializers.ModelSerializer):
    """Product list serializer (concise)"""
    primary_image = serializers.SerializerMethodField()
    category_names = serializers.SerializerMethodField()
    finance_code_name = serializers.CharField(source='finance_code.name', read_only=True, allow_null=True)
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'product_type',
            'short_description', 'price', 'compare_price',
            'primary_image', 'category_names', 'finance_code', 'finance_code_name',
            'is_active', 'is_featured', 'stock_quantity', 'language'
        ]
        read_only_fields = ['id']
    
    def get_primary_image(self, obj):
        """Get primary product image URL"""
        primary = obj.primary_image
        if primary and primary.media and primary.media.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary.media.file.url)
            return primary.media.file.url
        return None
    
    def get_category_names(self, obj):
        """Get category names"""
        return [cat.name for cat in obj.categories.all()]


class ProductDetailSerializer(serializers.ModelSerializer):
    """Product detail serializer (full)"""
    media = BaseMediaLinkSerializer(many=True, read_only=True, source='media_links')
    variants = ProductVariantSerializer(many=True, read_only=True)
    categories = ProductCategorySerializer(many=True, read_only=True)
    tags = ProductTagSerializer(many=True, read_only=True)
    
    # Finance code
    finance_code_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    category_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    tag_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of tag names to create if they don't exist"
    )
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'barcode', 'product_type', 'description',
            'short_description', 'price', 'compare_price', 'cost',
            'is_subscription', 'subscription_plan', 'categories', 'category_ids',
            'tags', 'tag_ids', 'tag_names', 'finance_code', 'finance_code_id',
            'track_inventory', 'stock_quantity', 'low_stock_threshold',
            'requires_shipping', 'weight', 'meta_title', 'meta_description',
            'is_active', 'is_featured', 'language', 'media', 'variants',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_price(self, value):
        """Validate price is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Price cannot be negative")
            if value > 999999.99:
                raise serializers.ValidationError("Price cannot exceed 999999.99")
        return value
    
    def validate_compare_price(self, value):
        """Validate compare_price is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Compare price cannot be negative")
        return value
    
    def validate_cost(self, value):
        """Validate cost is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Cost cannot be negative")
        return value
    
    def validate_stock_quantity(self, value):
        """Validate stock_quantity is non-negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Stock quantity cannot be negative")
        return value
    
    def validate_low_stock_threshold(self, value):
        """Validate low_stock_threshold is non-negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Low stock threshold cannot be negative")
        return value


class WarehouseBasicSerializer(serializers.ModelSerializer):
    """Basic warehouse serializer for Store"""
    class Meta:
        from bfg.delivery.models import Warehouse
        model = Warehouse
        fields = ['id', 'name', 'code']


class StoreSerializer(serializers.ModelSerializer):
    """Store serializer"""
    warehouses = WarehouseBasicSerializer(many=True, read_only=True)
    warehouse_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        help_text="List of warehouse IDs to associate with this store"
    )
    
    class Meta:
        model = Store
        fields = ['id', 'workspace', 'name', 'code', 'description', 'warehouses', 'warehouse_ids', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'workspace', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        warehouse_ids = validated_data.pop('warehouse_ids', [])
        store = Store.objects.create(**validated_data)
        if warehouse_ids:
            from bfg.delivery.models import Warehouse
            warehouses = Warehouse.objects.filter(id__in=warehouse_ids, workspace=store.workspace)
            store.warehouses.set(warehouses)
        return store
    
    def update(self, instance, validated_data):
        warehouse_ids = validated_data.pop('warehouse_ids', None)
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update warehouses if provided
        if warehouse_ids is not None:
            from bfg.delivery.models import Warehouse
            warehouses = Warehouse.objects.filter(id__in=warehouse_ids, workspace=instance.workspace)
            instance.warehouses.set(warehouses)
        
        return instance


# ============================================================================
# New Model Serializers (Shopify-like Features)
# ============================================================================

class SalesChannelSerializer(serializers.ModelSerializer):
    """Sales channel serializer"""
    product_count = serializers.SerializerMethodField()
    
    class Meta:
        model = SalesChannel
        fields = [
            'id', 'name', 'code', 'channel_type', 'description',
            'config', 'is_active', 'is_default', 'product_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_product_count(self, obj):
        """Get number of products in this channel"""
        return obj.product_listings.count()


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Subscription plan serializer"""
    subscription_count = serializers.SerializerMethodField()
    
    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'description', 'price', 'interval', 'interval_count',
            'trial_period_days', 'features', 'is_active', 'subscription_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_subscription_count(self, obj):
        """Get number of active subscriptions"""
        return obj.subscriptions.filter(status__in=['active', 'trialing']).count()


class ProductChannelListingSerializer(serializers.ModelSerializer):
    """Product channel listing serializer"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    
    class Meta:
        model = ProductChannelListing
        fields = [
            'id', 'product', 'product_name', 'channel', 'channel_name',
            'available_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ChannelCollectionSerializer(serializers.ModelSerializer):
    """Channel collection serializer"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    
    class Meta:
        model = ChannelCollection
        fields = [
            'id', 'category', 'category_name', 'channel', 'channel_name',
            'available_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ReturnLineItemSerializer(serializers.ModelSerializer):
    """Return line item serializer"""
    product_name = serializers.CharField(source='order_item.product_name', read_only=True)
    product_price = serializers.DecimalField(
        source='order_item.price', max_digits=10, decimal_places=2, read_only=True
    )
    
    class Meta:
        model = ReturnLineItem
        fields = [
            'id', 'order_item', 'product_name', 'product_price',
            'quantity', 'reason', 'restock_action'
        ]
        read_only_fields = ['id']


class ReturnSerializer(serializers.ModelSerializer):
    """Return request serializer"""
    items = ReturnLineItemSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    
    class Meta:
        model = Return
        fields = [
            'id', 'order', 'order_number', 'customer', 'customer_name',
            'return_number', 'status', 'reason_category', 'customer_note',
            'admin_note', 'closed_at', 'items',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'return_number', 'created_at', 'updated_at']
    
    def get_customer_name(self, obj):
        """Get customer full name"""
        if obj.customer and obj.customer.user:
            return obj.customer.user.get_full_name()
        return None


class CartItemSerializer(serializers.ModelSerializer):
    """Cart item serializer"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_slug = serializers.CharField(source='product.slug', read_only=True)
    variant_name = serializers.CharField(source='variant.name', read_only=True, allow_null=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = CartItem
        fields = [
            'id', 'product', 'product_name', 'product_slug',
            'variant', 'variant_name', 'quantity', 'price', 'subtotal'
        ]
        read_only_fields = ['id', 'price']
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value is None:
            raise serializers.ValidationError("Quantity is required")
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        if value > 10000:  # Reasonable upper limit
            raise serializers.ValidationError("Quantity cannot exceed 10000")
        return value


class CartSerializer(serializers.ModelSerializer):
    """Cart serializer with items"""
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Cart
        fields = [
            'id', 'customer', 'items', 'total', 'item_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'customer', 'created_at', 'updated_at']
    
    def get_total(self, obj):
        """Calculate cart total"""
        return sum(item.subtotal for item in obj.items.all())
    
    def get_item_count(self, obj):
        """Get total item count"""
        return obj.items.count()


class OrderItemSerializer(serializers.ModelSerializer):
    """Order item serializer"""
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'variant', 'product_name', 'variant_name',
            'sku', 'quantity', 'price', 'subtotal'
        ]
        read_only_fields = ['id', 'price', 'subtotal']
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value is None:
            raise serializers.ValidationError("Quantity is required")
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        if value > 10000:  # Reasonable upper limit
            raise serializers.ValidationError("Quantity cannot exceed 10000")
        return value


class OrderListSerializer(serializers.ModelSerializer):
    """Order list serializer (concise)"""
    customer_name = serializers.CharField(source='customer.user.get_full_name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    sales_channel_name = serializers.CharField(source='sales_channel.name', read_only=True, allow_null=True)
    item_count = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer', 'customer_name',
            'store', 'store_name', 'sales_channel', 'sales_channel_name',
            'status', 'payment_status',
            'total', 'item_count', 'created_at'
        ]
        read_only_fields = ['id', 'order_number', 'created_at']
    
    def get_item_count(self, obj):
        """Get order item count"""
        return obj.items.count()


class OrderCreateSerializer(serializers.ModelSerializer):
    """Order create serializer (for direct order creation)"""
    customer_id = serializers.IntegerField(write_only=True, required=False)
    store_id = serializers.IntegerField(write_only=True, required=True)
    shipping_address_id = serializers.IntegerField(write_only=True, required=True)
    billing_address_id = serializers.IntegerField(write_only=True, required=False)
    
    # Read fields for response
    id = serializers.IntegerField(read_only=True)
    order_number = serializers.CharField(read_only=True)
    customer = serializers.IntegerField(source='customer.id', read_only=True)
    store = serializers.IntegerField(source='store.id', read_only=True)
    
    # Security: All calculation fields must be read-only
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    shipping_cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    tax = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    discount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer', 'customer_id', 'store', 'store_id',
            'shipping_address_id', 'billing_address_id',
            'subtotal', 'shipping_cost', 'tax', 'discount', 'total',
            'status', 'payment_status', 'customer_note', 'admin_note',
            'created_at'
        ]
        read_only_fields = [
            'id', 'order_number', 'customer', 'store', 'created_at',
            'subtotal', 'shipping_cost', 'tax', 'discount', 'total'
        ]


class OrderDetailSerializer(serializers.ModelSerializer):
    """Order detail serializer (full)"""
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.user.get_full_name', read_only=True)
    customer = serializers.SerializerMethodField()
    store_name = serializers.CharField(source='store.name', read_only=True)
    sales_channel_name = serializers.CharField(source='sales_channel.name', read_only=True, allow_null=True)
    shipping_address = serializers.SerializerMethodField()
    billing_address = serializers.SerializerMethodField()
    shipping_address_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    billing_address_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    invoices = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    activities = serializers.SerializerMethodField()
    packages = serializers.SerializerMethodField()
    freight_service = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer', 'customer_name',
            'store', 'store_name', 'sales_channel', 'sales_channel_name',
            'status', 'payment_status',
            'subtotal', 'shipping_cost', 'tax', 'discount', 'total',
            'shipping_address', 'billing_address', 'shipping_address_id', 'billing_address_id',
            'customer_note', 'admin_note', 'items', 'packages', 'invoices', 'payments', 'activities',
            'freight_service',
            'created_at', 'updated_at',
            'paid_at', 'shipped_at', 'delivered_at'
        ]
        read_only_fields = [
            'id', 'order_number', 'created_at', 'updated_at',
            'paid_at', 'shipped_at', 'delivered_at'
        ]
    
    def get_customer(self, obj):
        """Get customer details"""
        if obj.customer:
            from bfg.common.serializers import CustomerDetailSerializer
            return CustomerDetailSerializer(obj.customer).data
        return None
    
    def get_shipping_address(self, obj):
        """Get shipping address details"""
        if obj.shipping_address:
            from bfg.common.serializers import AddressSerializer
            return AddressSerializer(obj.shipping_address).data
        return None
    
    def get_billing_address(self, obj):
        """Get billing address details"""
        if obj.billing_address:
            from bfg.common.serializers import AddressSerializer
            return AddressSerializer(obj.billing_address).data
        return None
    
    def get_invoices(self, obj):
        """Get invoices for this order"""
        from bfg.finance.serializers import InvoiceDetailSerializer
        invoices = obj.invoices.all().prefetch_related('items')
        return InvoiceDetailSerializer(invoices, many=True, context=self.context).data
    
    def get_payments(self, obj):
        """Get payments for this order"""
        from bfg.finance.serializers import PaymentSerializer
        payments = obj.payments.all()
        return PaymentSerializer(payments, many=True, context=self.context).data
    
    def get_packages(self, obj):
        """Get packages for this order (from delivery.Package)"""
        packages = obj.packages.select_related('template').all()
        return [
            {
                'id': pkg.id,
                'order': pkg.order.id if pkg.order else None,
                'package_number': pkg.package_number,
                'template': pkg.template.id if pkg.template else None,
                'template_name': pkg.template.name if pkg.template else None,
                'length': float(pkg.length) if pkg.length else 0,
                'width': float(pkg.width) if pkg.width else 0,
                'height': float(pkg.height) if pkg.height else 0,
                'weight': float(pkg.weight) if pkg.weight else 0,
                'quantity': pkg.pieces or 1,
                'volumetric_weight': float(pkg.volumetric_weight),
                'billing_weight': float(pkg.billing_weight),
                'total_billing_weight': float(pkg.total_billing_weight),
                'description': pkg.description,
                'notes': pkg.notes,
            }
            for pkg in packages
        ]
    
    def get_activities(self, obj):
        """Get order activity history from AuditLog"""
        from django.contrib.contenttypes.models import ContentType
        from bfg.common.models import AuditLog
        
        content_type = ContentType.objects.get_for_model(Order)
        audit_logs = AuditLog.objects.filter(
            workspace=obj.workspace,
            content_type=content_type,
            object_id=obj.id
        ).order_by('created_at')
        
        activities = []
        for log in audit_logs:
            # Determine color based on action and status changes
            color = 'primary'
            if log.action == 'create':
                color = 'primary'
            elif log.action == 'update':
                # Check if status changed to delivered
                if log.changes and 'status' in log.changes:
                    new_status = log.changes['status'].get('new', '')
                    if new_status == 'delivered':
                        color = 'success'
                    elif new_status == 'cancelled':
                        color = 'error'
            elif log.action == 'delete':
                color = 'error'
            
            activities.append({
                'id': log.id,
                'title': log.description or f"Order {log.action}",
                'description': log.description or '',
                'time': log.created_at.isoformat(),
                'action': log.action,
                'color': color,
            })
        
        return activities
    
    def get_freight_service(self, obj):
        """Get freight service information"""
        if obj.freight_service:
            return {
                'id': obj.freight_service.id,
                'name': obj.freight_service.name,
                'code': obj.freight_service.code,
                'carrier_name': obj.freight_service.carrier.name if obj.freight_service.carrier else None,
                'estimated_days_min': obj.freight_service.estimated_days_min,
                'estimated_days_max': obj.freight_service.estimated_days_max,
            }
        return None


class ProductReviewSerializer(serializers.ModelSerializer):
    """Product review serializer"""
    customer_name = serializers.CharField(source='customer.user.get_full_name', read_only=True)
    
    class Meta:
        model = ProductReview
        fields = [
            'id', 'product', 'customer', 'customer_name', 'rating',
            'title', 'comment', 'is_verified_purchase', 'is_approved',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'customer', 'is_verified_purchase', 'created_at', 'updated_at']
    
    def validate_rating(self, value):
        """Validate rating is between 1-5"""
        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating must be between 1 and 5')
        return value


# ============================================================================
# Package Template & Order Package Serializers
# ============================================================================

class OrderPackageSerializer(serializers.ModelSerializer):
    """Serializer for Package when used with Order (order fulfillment)"""
    template_name = serializers.CharField(source='template.name', read_only=True, allow_null=True)
    volumetric_weight = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    billing_weight = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_billing_weight = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    quantity = serializers.IntegerField(source='pieces', read_only=True)
    
    class Meta:
        model = Package
        fields = [
            'id', 'order', 'template', 'template_name', 'package_number',
            'length', 'width', 'height', 'weight', 'quantity',
            'volumetric_weight', 'billing_weight', 'total_billing_weight',
            'description', 'notes',
            'created_at'
        ]
        read_only_fields = [
            'id', 'volumetric_weight', 'billing_weight', 
            'total_billing_weight', 'created_at'
        ]


class OrderPackageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating order packages with template support"""
    quantity = serializers.IntegerField(source='pieces', default=1)
    package_number = serializers.CharField(required=False, allow_blank=True)
    
    class Meta:
        model = Package
        fields = [
            'template', 'package_number', 'length', 'width', 'height', 
            'weight', 'quantity', 'description', 'notes'
        ]
    
    def validate(self, attrs):
        """Validate and copy dimensions from template if provided"""
        template = attrs.get('template')
        
        # If template provided and dimensions not specified, copy from template
        if template:
            if 'length' not in attrs or attrs.get('length') is None:
                attrs['length'] = template.length
            if 'width' not in attrs or attrs.get('width') is None:
                attrs['width'] = template.width
            if 'height' not in attrs or attrs.get('height') is None:
                attrs['height'] = template.height
        
        return attrs

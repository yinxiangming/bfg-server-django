"""
Storefront API Serializers

Simplified serializers for customer-facing storefront API
Only exposes necessary fields, hides sensitive information
"""
from rest_framework import serializers
from decimal import Decimal
from bfg.common.models import Address
from bfg.shop.models import (
    Product, ProductVariant, ProductCategory, ProductTag,
    Cart, CartItem, Order, OrderItem, ProductReview
)
from bfg.common.serializers import MediaLinkSerializer
from bfg.finance.models import Payment, PaymentGateway


class StorefrontProductVariantSerializer(serializers.ModelSerializer):
    """Storefront product variant serializer - simplified"""
    stock_available = serializers.SerializerMethodField()
    stock_quantity = serializers.IntegerField(read_only=True)
    stock_reserved = serializers.SerializerMethodField()
    stock_by_warehouse = serializers.SerializerMethodField()
    options = serializers.JSONField(read_only=True, help_text="Variant options (size, color, etc.)")
    
    class Meta:
        model = ProductVariant
        fields = ['id', 'name', 'sku', 'price', 'compare_price', 'options', 'stock_quantity', 'stock_available', 'stock_reserved', 'stock_by_warehouse', 'is_active']
        read_only_fields = ['id', 'options']
    
    def get_stock_available(self, obj):
        """Get available stock quantity (total - reserved)"""
        # Calculate from VariantInventory if available
        from django.db.models import Sum, F
        from bfg.shop.models import VariantInventory
        
        total_available = VariantInventory.objects.filter(
            variant=obj
        ).aggregate(
            available=Sum(F('quantity') - F('reserved'))
        )['available']
        
        if total_available is not None:
            return max(0, total_available)
        
        # Fallback to variant's stock_quantity
        return max(0, obj.stock_quantity)
    
    def get_stock_reserved(self, obj):
        """Get total reserved stock quantity"""
        from django.db.models import Sum
        from bfg.shop.models import VariantInventory
        
        total_reserved = VariantInventory.objects.filter(
            variant=obj
        ).aggregate(
            reserved=Sum('reserved')
        )['reserved']
        
        return total_reserved or 0
    
    def get_stock_by_warehouse(self, obj):
        """Get stock breakdown by warehouse"""
        from bfg.shop.models import VariantInventory
        
        inventories = VariantInventory.objects.filter(
            variant=obj
        ).select_related('warehouse')
        
        return [
            {
                'warehouse_id': inv.warehouse.id,
                'warehouse_name': inv.warehouse.name,
                'warehouse_code': inv.warehouse.code,
                'quantity': inv.quantity,
                'reserved': inv.reserved,
                'available': inv.available,
            }
            for inv in inventories
        ]


# StorefrontProductMediaSerializer removed - use MediaLinkSerializer from bfg.common.serializers


class StorefrontProductSerializer(serializers.ModelSerializer):
    """Storefront product serializer - simplified"""
    media = MediaLinkSerializer(many=True, read_only=True, source='media_links')
    variants = StorefrontProductVariantSerializer(many=True, read_only=True)
    categories = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    discount_percentage = serializers.SerializerMethodField()
    is_new = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'slug', 'name', 'price', 'compare_price', 'product_type',
            'description', 'short_description', 'media', 'variants',
            'categories', 'tags', 'primary_image', 'images',
            'discount_percentage', 'is_new', 'is_featured', 'rating', 'reviews_count'
        ]
        read_only_fields = ['id']
    
    def get_categories(self, obj):
        """Get category names"""
        return [{'id': cat.id, 'name': cat.name, 'slug': cat.slug} 
                for cat in obj.categories.filter(is_active=True)]
    
    def get_tags(self, obj):
        """Get tag names"""
        return [{'id': tag.id, 'name': tag.name, 'slug': tag.slug} 
                for tag in obj.tags.all()]
    
    def get_primary_image(self, obj):
        """Get primary product image URL"""
        primary_media = obj.primary_image
        if primary_media and primary_media.media:
            request = self.context.get('request')
            if primary_media.media.external_url:
                return primary_media.media.external_url
            elif primary_media.media.file and request:
                return request.build_absolute_uri(primary_media.media.file.url)
            elif primary_media.media.file:
                return primary_media.media.file.url
        return None
    
    def get_images(self, obj):
        """Get all product image URLs"""
        request = self.context.get('request')
        images = []
        for ml in obj.media_links.filter(media__media_type='image').select_related('media').order_by('position'):
            if ml.media:
                if ml.media.external_url:
                    images.append(ml.media.external_url)
                elif ml.media.file:
                    if request:
                        images.append(request.build_absolute_uri(ml.media.file.url))
                    else:
                        images.append(ml.media.file.url)
        return images
    
    def get_discount_percentage(self, obj):
        """Calculate discount percentage"""
        if obj.compare_price and obj.compare_price > obj.price:
            discount = ((obj.compare_price - obj.price) / obj.compare_price) * 100
            return round(float(discount), 1)
        return None
    
    def get_is_new(self, obj):
        """Check if product is new (created within last 30 days)"""
        from django.utils import timezone
        from datetime import timedelta
        thirty_days_ago = timezone.now() - timedelta(days=30)
        return obj.created_at >= thirty_days_ago
    
    def get_rating(self, obj):
        """Get average rating from approved reviews"""
        from django.db.models import Avg
        from bfg.shop.models import ProductReview
        
        avg_rating = ProductReview.objects.filter(
            product=obj,
            is_approved=True
        ).aggregate(avg_rating=Avg('rating'))['avg_rating']
        
        if avg_rating:
            return round(float(avg_rating), 1)
        return None
    
    def get_reviews_count(self, obj):
        """Get count of approved reviews"""
        from bfg.shop.models import ProductReview

        return ProductReview.objects.filter(
            product=obj,
            is_approved=True
        ).count()


class StorefrontCategorySerializer(serializers.ModelSerializer):
    """Storefront category serializer - simplified"""
    children = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'slug', 'description', 'children', 'image_url', 'product_count']
        read_only_fields = ['id']
    
    def get_children(self, obj):
        """Get children categories recursively"""
        children = obj.children.filter(is_active=True).order_by('order', 'name')
        return StorefrontCategorySerializer(children, many=True, context=self.context).data
    
    def get_image_url(self, obj):
        """Get category image URL"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
    
    def get_product_count(self, obj):
        """Get product count for this category"""
        return obj.products.filter(is_active=True).count()


class StorefrontCartItemSerializer(serializers.ModelSerializer):
    """Storefront cart item serializer"""
    item_id = serializers.IntegerField(source='id', read_only=True)
    product_id = serializers.IntegerField(source='product.id', read_only=True)
    variant_id = serializers.IntegerField(source='variant.id', read_only=True, allow_null=True)
    name = serializers.CharField(source='product.name', read_only=True)
    variant_name = serializers.CharField(source='variant.name', read_only=True, allow_null=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    image_url = serializers.SerializerMethodField()
    variant_options = serializers.SerializerMethodField()
    
    class Meta:
        model = CartItem
        fields = ['item_id', 'product_id', 'variant_id', 'name', 'variant_name', 
                  'price', 'quantity', 'subtotal', 'image_url', 'variant_options']
        read_only_fields = ['item_id', 'product_id', 'variant_id', 'name', 
                           'variant_name', 'price', 'subtotal', 'image_url', 'variant_options']
    
    def get_image_url(self, obj):
        """Get product image URL"""
        primary_media = obj.product.primary_image
        if primary_media and primary_media.media:
            request = self.context.get('request')
            if primary_media.media.external_url:
                return primary_media.media.external_url
            elif primary_media.media.file:
                if request:
                    return request.build_absolute_uri(primary_media.media.file.url)
                return primary_media.media.file.url
        return None
    
    def get_variant_options(self, obj):
        """Get variant options (size, color, etc.)"""
        if obj.variant and obj.variant.options:
            return obj.variant.options
        return {}


class StorefrontCartSerializer(serializers.ModelSerializer):
    """Storefront cart serializer"""
    items = StorefrontCartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    
    class Meta:
        model = Cart
        fields = ['id', 'items', 'total']
        read_only_fields = ['id']
    
    def get_total(self, obj):
        """Calculate cart total"""
        return sum(item.subtotal for item in obj.items.all())


class StorefrontAddressSerializer(serializers.ModelSerializer):
    """Storefront address serializer - simplified"""
    
    class Meta:
        model = Address
        fields = [
            'id', 'full_name', 'phone', 'email', 'company',
            'address_line1', 'address_line2', 'city', 'state',
            'postal_code', 'country', 'is_default'
        ]
        read_only_fields = ['id']
    
    def validate_postal_code(self, value):
        """Validate postal code format"""
        if not value:
            raise serializers.ValidationError("Postal code is required")
        return value
    
    def validate_country(self, value):
        """Validate country code"""
        if value and len(value) != 2:
            raise serializers.ValidationError("Country must be a 2-letter ISO code")
        return value


class StorefrontOrderItemSerializer(serializers.ModelSerializer):
    """Storefront order item serializer"""
    product_name = serializers.CharField(read_only=True)
    variant_name = serializers.CharField(read_only=True, allow_null=True)
    sku = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ['product_name', 'variant_name', 'sku', 'quantity', 'price', 'subtotal', 'image_url']
        read_only_fields = ['product_name', 'variant_name', 'sku', 'price', 'subtotal', 'image_url']

    def get_image_url(self, obj):
        """Product primary image URL for order item"""
        primary_media = obj.product.primary_image if obj.product_id else None
        if not primary_media or not getattr(primary_media, 'media', None):
            return None
        media = primary_media.media
        request = self.context.get('request')
        if media.external_url:
            return media.external_url
        if media.file:
            if request:
                return request.build_absolute_uri(media.file.url)
            return media.file.url
        return None


class StorefrontOrderSerializer(serializers.ModelSerializer):
    """Storefront order serializer - simplified"""
    items = StorefrontOrderItemSerializer(many=True, read_only=True)
    amounts = serializers.SerializerMethodField()
    addresses = serializers.SerializerMethodField()
    timestamps = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    activities = serializers.SerializerMethodField()
    freight_service = serializers.SerializerMethodField()
    packages = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'status', 'payment_status',
            'amounts', 'addresses', 'items', 'timestamps', 'customer', 'activities', 'freight_service', 'packages'
        ]
        read_only_fields = ['id', 'order_number']
    
    def get_amounts(self, obj):
        """Get order amounts"""
        return {
            'subtotal': obj.subtotal,
            'shipping_cost': obj.shipping_cost or Decimal('0.00'),
            'tax': obj.tax or Decimal('0.00'),
            'discount': obj.discount or Decimal('0.00'),
            'total': obj.total
        }
    
    def get_addresses(self, obj):
        """Get shipping and billing addresses"""
        return {
            'shipping': StorefrontAddressSerializer(obj.shipping_address).data if obj.shipping_address else None,
            'billing': StorefrontAddressSerializer(obj.billing_address).data if obj.billing_address else None
        }
    
    def get_timestamps(self, obj):
        """Get order timestamps"""
        return {
            'created_at': obj.created_at,
            'updated_at': obj.updated_at,
            'paid_at': obj.paid_at,
            'shipped_at': obj.shipped_at,
            'delivered_at': obj.delivered_at
        }
    
    def get_customer(self, obj):
        """Get customer details including user info"""
        if obj.customer:
            from bfg.common.serializers import CustomerDetailSerializer
            return CustomerDetailSerializer(obj.customer, context=self.context).data
        return None
    
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
    
    def get_packages(self, obj):
        """Get packages for this order (from delivery.Package)"""
        from bfg.delivery.models import Package
        packages = Package.objects.filter(order=obj).select_related('template')
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
                'volumetric_weight': float(pkg.volumetric_weight) if pkg.volumetric_weight else 0,
                'billing_weight': float(pkg.billing_weight) if pkg.billing_weight else 0,
                'total_billing_weight': float(pkg.total_billing_weight) if pkg.total_billing_weight else 0,
                'description': pkg.description,
                'notes': pkg.notes,
            }
            for pkg in packages
        ]
    
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


class StorefrontPaymentSerializer(serializers.ModelSerializer):
    """Storefront payment serializer - simplified"""
    
    class Meta:
        model = Payment
        fields = [
            'id', 'payment_number', 'status', 'amount', 'currency',
            'gateway', 'gateway_transaction_id'
        ]
        read_only_fields = ['id', 'payment_number']
    
    currency = serializers.CharField(source='currency.code', read_only=True)
    gateway = serializers.CharField(source='gateway.name', read_only=True)


class PaymentIntentSerializer(serializers.Serializer):
    """Payment intent request serializer"""
    order_id = serializers.IntegerField(required=True)
    gateway_id = serializers.IntegerField(required=False, allow_null=True)
    payment_method_id = serializers.IntegerField(required=False, allow_null=True)
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    save_card = serializers.BooleanField(required=False, default=False)
    
    def validate_order_id(self, value):
        """Validate order exists and belongs to customer"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required")
        
        from bfg.shop.models import Order
        
        is_staff = getattr(request, 'is_staff_member', False) or request.user.is_superuser
        
        try:
            order = Order.objects.get(id=value, workspace=request.workspace)
            if not is_staff:
                from bfg.common.models import Customer
                
                customer = Customer.objects.filter(
                    user=request.user,
                    workspace=request.workspace
                ).first()
                
                if not customer:
                    raise serializers.ValidationError("Customer profile not found")
                
                if order.customer != customer:
                    raise serializers.ValidationError("Order does not belong to current customer")
        except Order.DoesNotExist:
            raise serializers.ValidationError("Order not found")
        
        return value


class PaymentIntentResponseSerializer(serializers.Serializer):
    """Payment intent response serializer"""
    payment_id = serializers.IntegerField()
    payment_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField()
    gateway_payload = serializers.DictField(help_text="Gateway-specific payload (e.g., client_secret, code_url)")
    status = serializers.CharField()


class StorefrontPaymentGatewaySerializer(serializers.ModelSerializer):
    """Storefront payment gateway serializer - public info only"""
    display_info = serializers.SerializerMethodField()
    supported_clients = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentGateway
        fields = ['id', 'name', 'gateway_type', 'is_active', 'display_info', 'supported_clients']
    
    def get_supported_clients(self, obj):
        """From plugin: empty list means all clients (web, android, ios, mp) supported."""
        from bfg.finance.gateways.loader import GatewayLoader
        info = GatewayLoader.get_plugin_info(obj.gateway_type)
        return (info or {}).get('supported_clients') or []
    
    def get_display_info(self, obj):
        """Get public display info from gateway plugin (get_payment_page_display_params)."""
        from bfg.finance.gateways.loader import get_gateway_plugin
        try:
            plugin = get_gateway_plugin(obj)
            if plugin:
                return plugin.get_payment_page_display_params()
        except Exception:
            pass
        # Fallback when no plugin or plugin fails (e.g. invalid config)
        config = obj.get_active_config() or {}
        if obj.gateway_type in ('custom', 'bank_transfer'):
            return {
                'bank_name': config.get('bank_name', ''),
                'account_name': config.get('account_name', ''),
                'account_number': config.get('account_number', ''),
                'routing_number': config.get('routing_number', ''),
                'swift_code': config.get('swift_code', ''),
                'instructions': config.get('instructions') or config.get('note', ''),
            }
        if obj.gateway_type == 'stripe':
            return {
                'publishable_key': config.get('publishable_key', ''),
                'supports_saved_cards': True,
            }
        if obj.gateway_type == 'paypal':
            return {'client_id': config.get('client_id', '')}
        return {}


class StorefrontProductReviewSerializer(serializers.ModelSerializer):
    """Storefront product review serializer"""
    customer_name = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductReview
        fields = [
            'id', 'rating', 'title', 'comment', 'images',
            'is_verified_purchase', 'helpful_count',
            'customer_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'customer_name', 'is_verified_purchase', 'helpful_count', 'created_at', 'updated_at']
    
    def get_customer_name(self, obj):
        """Get customer name"""
        if obj.customer and obj.customer.user:
            full_name = obj.customer.user.get_full_name()
            if full_name:
                return full_name
            return obj.customer.user.username
        return None
    
    def get_images(self, obj):
        """Get review images as full URLs"""
        if not obj.images:
            return []
        
        request = self.context.get('request')
        image_urls = []
        
        for image_path in obj.images:
            if image_path.startswith('http://') or image_path.startswith('https://'):
                image_urls.append(image_path)
            elif image_path.startswith('/media/'):
                if request:
                    image_urls.append(request.build_absolute_uri(image_path))
                else:
                    image_urls.append(image_path)
            else:
                # Assume it's a relative path, prepend /media/
                media_path = f'/media/{image_path}' if not image_path.startswith('/') else image_path
                if request:
                    image_urls.append(request.build_absolute_uri(media_path))
                else:
                    image_urls.append(media_path)
        
        return image_urls
    
    def validate_rating(self, value):
        """Validate rating is between 1-5"""
        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating must be between 1 and 5')
        return value


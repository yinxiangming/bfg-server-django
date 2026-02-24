"""
Storefront API ViewSets

Customer-facing API endpoints for storefront functionality
Routes are prefixed with /api/store/
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication as BearerTokenAuthentication
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from django.contrib.auth import get_user_model
import uuid

from bfg.common.models import Customer, Address
from bfg.shop.models import (
    Product, ProductVariant, ProductCategory, ProductTag,
    Cart, CartItem, Order, Store, ProductReview
)
from bfg.shop.serializers.storefront import (
    StorefrontProductSerializer, StorefrontCategorySerializer,
    StorefrontCartSerializer, StorefrontCartItemSerializer,
    StorefrontOrderSerializer,
    StorefrontPaymentSerializer, PaymentIntentSerializer,
    PaymentIntentResponseSerializer, StorefrontProductReviewSerializer
)
from bfg.common.serializers import AddressSerializer
from bfg.common.models import Address, Customer
from bfg.common.services import CustomerService
from bfg.common.utils import get_required_workspace
from django.contrib.contenttypes.models import ContentType
from bfg.shop.services import CartService, OrderService
from bfg.shop.exceptions import InsufficientStock
from bfg.finance.models import Payment, PaymentGateway, Currency
from bfg.finance.services import PaymentService

User = get_user_model()

class StorefrontProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Storefront product browsing ViewSet"""
    serializer_class = StorefrontProductSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = 'slug'
    lookup_url_kwarg = 'id_or_slug'
    
    def get_queryset(self):
        """Get active products with filtering"""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum
        
        workspace = self.request.workspace
        queryset = Product.objects.filter(
            workspace=workspace,
            is_active=True
        ).prefetch_related(
            'media_links__media', 'variants', 'categories', 'tags'
        )
        
        # Filtering
        q = self.request.query_params.get('q')
        if q:
            queryset = queryset.filter(name__icontains=q)
        
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(categories__slug=category)
        
        tag = self.request.query_params.get('tag')
        if tag:
            queryset = queryset.filter(tags__slug=tag)
        
        # Featured products filter
        featured = self.request.query_params.get('featured')
        if featured and featured.lower() == 'true':
            queryset = queryset.filter(is_featured=True)
        
        # New products filter (created within last 30 days)
        is_new = self.request.query_params.get('is_new')
        if is_new and is_new.lower() == 'true':
            thirty_days_ago = timezone.now() - timedelta(days=30)
            queryset = queryset.filter(created_at__gte=thirty_days_ago)
        
        # Price filtering
        min_price = self.request.query_params.get('min_price')
        if min_price:
            try:
                queryset = queryset.filter(price__gte=Decimal(min_price))
            except (ValueError, TypeError):
                pass
        
        max_price = self.request.query_params.get('max_price')
        if max_price:
            try:
                queryset = queryset.filter(price__lte=Decimal(max_price))
            except (ValueError, TypeError):
                pass
        
        # Bestseller filter (products with most order items)
        bestseller = self.request.query_params.get('bestseller')
        if bestseller and bestseller.lower() == 'true':
            queryset = queryset.annotate(
                total_sold=Sum('orderitem__quantity')
            ).order_by('-total_sold', '-created_at')
        else:
            # Regular sorting
            sort = self.request.query_params.get('sort', 'created_at')
            if sort == 'price_asc':
                queryset = queryset.order_by('price')
            elif sort == 'price_desc':
                queryset = queryset.order_by('-price')
            elif sort == 'name':
                queryset = queryset.order_by('name')
            elif sort == 'sales':
                # Sort by order items count
                queryset = queryset.annotate(
                    total_sold=Sum('orderitem__quantity')
                ).order_by('-total_sold', '-created_at')
            else:
                queryset = queryset.order_by('-created_at')
        
        # Apply distinct before any slicing
        queryset = queryset.distinct()
        
        # Limit results if specified (must be after distinct)
        limit = self.request.query_params.get('limit')
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except (ValueError, TypeError):
                pass
        
        return queryset
    
    def retrieve(self, request, *args, **kwargs):
        """Retrieve product by ID or slug"""
        lookup_value = kwargs.get(self.lookup_url_kwarg)
        
        # Try to get by ID first, then by slug
        try:
            product_id = int(lookup_value)
            product = self.get_queryset().get(id=product_id)
        except (ValueError, Product.DoesNotExist):
            try:
                product = self.get_queryset().get(slug=lookup_value)
            except Product.DoesNotExist:
                raise NotFound("Product not found")
        
        serializer = self.get_serializer(product)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get', 'post'], url_path='reviews')
    def reviews(self, request, *args, **kwargs):
        """Get or create product reviews"""
        # Get product using the same logic as retrieve method
        # since we use custom lookup (id or slug)
        lookup_value = kwargs.get(self.lookup_url_kwarg)
        if lookup_value:
            try:
                product_id = int(lookup_value)
                product = self.get_queryset().get(id=product_id)
            except (ValueError, Product.DoesNotExist):
                try:
                    product = self.get_queryset().get(slug=lookup_value)
                except Product.DoesNotExist:
                    from rest_framework.exceptions import NotFound
                    raise NotFound("Product not found")
        else:
            product = self.get_object()
        
        if request.method == 'GET':
            # Get reviews for product
            queryset = ProductReview.objects.filter(
                product=product,
                is_approved=True
            ).select_related('customer', 'customer__user').order_by('-created_at')
            
            # Optional filtering
            rating_filter = request.query_params.get('rating')
            if rating_filter:
                try:
                    rating = int(rating_filter)
                    if 1 <= rating <= 5:
                        queryset = queryset.filter(rating=rating)
                except (ValueError, TypeError):
                    pass
            
            serializer = StorefrontProductReviewSerializer(queryset, many=True, context={'request': request})
            return Response(serializer.data)
        
        elif request.method == 'POST':
            # Create review (requires authentication)
            if not request.user.is_authenticated:
                return Response(
                    {'detail': 'Authentication required'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if customer already reviewed this product
            customer, _ = Customer.objects.get_or_create(
                workspace=request.workspace,
                user=request.user,
                defaults={'is_active': True}
            )
            
            existing_review = ProductReview.objects.filter(
                product=product,
                customer=customer
            ).first()
            
            if existing_review:
                return Response(
                    {'detail': 'You have already reviewed this product'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create review
            serializer = StorefrontProductReviewSerializer(
                data=request.data,
                context={'request': request}
            )
            serializer.is_valid(raise_exception=True)
            
            # Check if this is a verified purchase
            is_verified = False
            order_id = request.data.get('order_id')
            if order_id:
                try:
                    order = Order.objects.get(
                        id=order_id,
                        customer=customer,
                        workspace=request.workspace
                    )
                    # Verify product is in order
                    if order.items.filter(product=product).exists():
                        is_verified = True
                        serializer.save(
                            workspace=request.workspace,
                            product=product,
                            customer=customer,
                            order=order,
                            is_verified_purchase=True,
                            is_approved=False  # Require approval for new reviews
                        )
                except Order.DoesNotExist:
                    pass
            
            if not is_verified:
                serializer.save(
                    workspace=request.workspace,
                    product=product,
                    customer=customer,
                    is_verified_purchase=False,
                    is_approved=False  # Require approval for new reviews
                )
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)


class StorefrontAddressViewSet(viewsets.ModelViewSet):
    """
    Storefront Address ViewSet - /api/store/addresses/

    Mirrors MeAddressViewSet logic without importing it to avoid circular deps.
    """
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Get addresses for current customer"""
        # Ensure workspace is set
        workspace = get_required_workspace(self.request)

        service = CustomerService(workspace=workspace, user=self.request.user)
        customer = service.get_customer_by_user(self.request.user, workspace)
        if not customer:
            return Address.objects.none()

        customer_type = ContentType.objects.get_for_model(Customer)
        return Address.objects.filter(
            workspace=customer.workspace,
            content_type=customer_type,
            object_id=customer.id
        ).order_by('-is_default', '-created_at')

    def perform_create(self, serializer):
        """Create address for current customer"""
        workspace = get_required_workspace(self.request)

        service = CustomerService(workspace=workspace, user=self.request.user)
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=workspace,
            defaults={'is_active': True}
        )

        customer_type = ContentType.objects.get_for_model(Customer)

        serializer.save(
            workspace=customer.workspace,
            content_type=customer_type,
            object_id=customer.id
        )

    @action(detail=False, methods=['get'])
    def default(self, request):
        """Get default address"""
        queryset = self.get_queryset().filter(is_default=True).first()
        if not queryset:
            return Response(
                {'detail': 'No default address found'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = self.get_serializer(queryset)
        return Response(serializer.data)


class StorefrontCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Storefront category ViewSet"""
    serializer_class = StorefrontCategorySerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def get_queryset(self):
        """Get active categories"""
        workspace = self.request.workspace
        language = self.request.query_params.get('lang', 'en')
        
        queryset = ProductCategory.objects.filter(
            workspace=workspace,
            is_active=True,
            language=language
        ).select_related('parent').prefetch_related('children')
        
        # If tree=true, return only root categories
        if self.request.query_params.get('tree', '').lower() == 'true':
            queryset = queryset.filter(parent__isnull=True)
        
        return queryset.order_by('order', 'name')


class StorefrontCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Storefront category ViewSet"""
    serializer_class = StorefrontCategorySerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def get_queryset(self):
        """Get active categories"""
        workspace = self.request.workspace
        language = self.request.query_params.get('lang', 'en')
        
        queryset = ProductCategory.objects.filter(
            workspace=workspace,
            is_active=True,
            language=language
        ).select_related('parent').prefetch_related('children')
        
        # If tree=true, return only root categories
        if self.request.query_params.get('tree', '').lower() == 'true':
            queryset = queryset.filter(parent__isnull=True)
        
        return queryset.order_by('order', 'name')


class StorefrontCartViewSet(viewsets.GenericViewSet):
    """Storefront cart ViewSet - supports anonymous and authenticated users"""
    serializer_class = StorefrontCartSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def _get_workspace(self, request):
        """
        Get workspace from request, with fallback to Site domain lookup.
        This ensures workspace is available even for guest users.
        
        Returns:
            Workspace instance or None
        """
        workspace = getattr(request, 'workspace', None)
        
        # If workspace not set by middleware, try to get from Site by domain
        if not workspace:
            hostname = request.get_host().split(':')[0]  # Remove port if present
            try:
                from bfg.web.models import Site
                site = Site.objects.filter(domain=hostname, is_active=True).first()
                if site:
                    workspace = site.workspace
            except (ImportError, AttributeError):
                pass
        
        # Last resort: get first active workspace
        if not workspace:
            from bfg.common.models import Workspace
            workspace = Workspace.objects.filter(is_active=True).first()
        
        return workspace
    
    @action(detail=False, methods=['get'])
    def default_store(self, request):
        """
        Get default active store for checkout
        Public endpoint - no authentication required
        GET /api/store/cart/default_store/
        
        Workspace is determined by:
        1. request.workspace (set by WorkspaceMiddleware)
        2. Site.domain lookup (fallback for guest users)
        3. First active workspace (last resort)
        """
        try:
            workspace = self._get_workspace(request)
            
            if not workspace:
                return Response(
                    {'detail': 'No active workspace found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            store = Store.objects.filter(
                workspace=workspace,
                is_active=True
            ).order_by('-created_at').first()
            
            if not store:
                return Response(
                    {'detail': 'No active store found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            default_currency_code = 'USD'
            if hasattr(workspace, 'workspace_settings') and workspace.workspace_settings:
                default_currency_code = workspace.workspace_settings.default_currency or 'USD'
            currency = None
            try:
                currency = Currency.objects.get(code=default_currency_code, is_active=True)
            except Currency.DoesNotExist:
                currency = Currency.objects.filter(is_active=True).first()
            payload = {
                'id': store.id,
                'name': store.name,
                'code': store.code
            }
            if currency:
                payload['currency_code'] = currency.code
                payload['currency_symbol'] = currency.symbol
            return Response(payload)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _get_or_create_cart(self):
        """Helper to get or create cart for current user/session"""
        workspace = self._get_workspace(self.request)
        if not workspace:
            raise ValidationError('Workspace is required')
        
        service = CartService(
            workspace=workspace,
            user=self.request.user if self.request.user.is_authenticated else None
        )
        
        if self.request.user.is_authenticated:
            customer, _ = Customer.objects.get_or_create(
                workspace=workspace,
                user=self.request.user,
                defaults={'is_active': True}
            )
            # Prefer X-Cart-ID when present (e.g. mini-program without shared session)
            cart_id_header = self.request.headers.get('X-Cart-ID')
            if cart_id_header:
                try:
                    cart_id = int(cart_id_header.strip())
                    cart = Cart.objects.filter(
                        id=cart_id,
                        workspace=workspace
                    ).first()
                    if cart:
                        if cart.customer is None:
                            cart.customer = customer
                            cart.save(update_fields=['customer'])
                        elif cart.customer != customer:
                            cart = None
                        if cart:
                            return cart
                except (ValueError, TypeError):
                    pass
            session_key = self.request.session.session_key
            if session_key:
                cart = service.merge_guest_cart_to_customer(session_key, customer)
            else:
                cart = service.get_or_create_cart(customer)
        else:
            # Anonymous: prefer X-Cart-ID header when session is not shared (e.g. mini-program)
            cart_id_header = self.request.headers.get('X-Cart-ID')
            if cart_id_header:
                try:
                    cart_id = int(cart_id_header.strip())
                    cart = Cart.objects.filter(
                        id=cart_id,
                        workspace=workspace,
                        customer__isnull=True
                    ).first()
                    if cart:
                        return cart
                except (ValueError, TypeError):
                    pass
            if not self.request.session.session_key:
                self.request.session.create()
            session_key = self.request.session.session_key
            cart = service.get_or_create_guest_cart(session_key)
        return cart
    
    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get or create current user's cart"""
        cart = self._get_or_create_cart()
        serializer = self.get_serializer(cart)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def preview(self, request):
        """
        Get cart preview with discount calculation
        Returns price breakdown including discount, shipping, tax, and total
        
        Query params:
            shipping_method: Shipping method ('standard' or 'express', default: 'standard')
            freight_service_id: FreightService ID (preferred over shipping_method)
        """
        from decimal import Decimal
        
        cart = self._get_or_create_cart()
        
        # Get freight_service_id (preferred) or shipping_method (backward compatibility)
        freight_service_id = request.query_params.get('freight_service_id')
        shipping_method = request.query_params.get('shipping_method', 'standard')
        
        # Use unified price calculation from OrderService
        from bfg.shop.services import OrderService
        order_service = OrderService(
            workspace=request.workspace,
            user=request.user if request.user.is_authenticated else None
        )
        
        # Try to get default address for tax calculation (optional)
        shipping_address = None
        if request.user.is_authenticated:
            try:
                from bfg.common.models import Customer, Address
                customer, _ = Customer.objects.get_or_create(
                    user=request.user,
                    workspace=request.workspace,
                    defaults={'is_active': True}
                )
                # Try to get default address
                shipping_address = Address.objects.filter(
                    workspace=request.workspace,
                    content_object=customer
                ).first()
            except Exception:
                pass  # Ignore errors, will use default tax rate
        
        totals = order_service.calculate_order_totals(
            cart=cart,
            shipping_method=shipping_method if not freight_service_id else None,
            freight_service_id=int(freight_service_id) if freight_service_id else None,
            coupon_code=None,  # No coupon code for preview
            gift_card_code=None,  # No gift card for preview
            user=request.user if request.user.is_authenticated else None,
            shipping_address=shipping_address
        )
        
        return Response({
            'subtotal': str(totals['subtotal']),
            'discount': str(totals['discount']),
            'shipping_cost': str(totals['shipping_cost']),
            'tax': str(totals['tax']),
            'total': str(totals['total']),
            'shipping_discount': str(totals['shipping_discount']) if totals['shipping_discount'] > Decimal('0.00') else None
        })
    
    @action(detail=False, methods=['post'])
    def add_item(self, request):
        """Add item to cart"""
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
            product = Product.objects.get(id=product_id, workspace=request.workspace, is_active=True)
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
        except InsufficientStock as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            # Catch any other unexpected exceptions
            import traceback
            traceback.print_exc()
            return Response(
                {'detail': f'An error occurred: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                return Response(
                    {'detail': 'Quantity must be greater than 0'},
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
    
    @action(detail=False, methods=['post'], authentication_classes=[BearerTokenAuthentication], permission_classes=[IsAuthenticated])
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
        customer_note = request.data.get('customer_note', '')
        freight_service_id = request.data.get('freight_service_id')  # Preferred
        shipping_method = request.data.get('shipping_method')  # Backward compatibility: 'standard' or 'express'
        shipping_cost = request.data.get('shipping_cost')  # Backward compatibility
        tax = request.data.get('tax')  # Backward compatibility
        
        if not store_id or not shipping_address_id:
            return Response(
                {'detail': 'store and shipping_address are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            store = Store.objects.get(id=store_id, workspace=request.workspace)
            shipping_address = Address.objects.get(id=shipping_address_id)
            
            # Verify address belongs to customer
            customer, _ = Customer.objects.get_or_create(
                user=request.user,
                workspace=request.workspace,
                defaults={'is_active': True}
            )
            
            # Check if address belongs to customer (simplified check)
            if shipping_address.content_object != customer:
                return Response(
                    {'detail': 'Shipping address not found or does not belong to you'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            billing_address = None
            if billing_address_id:
                billing_address = Address.objects.get(id=billing_address_id)
                if billing_address.content_object != customer:
                    return Response(
                        {'detail': 'Billing address not found or does not belong to you'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            
            order_service = OrderService(
                workspace=request.workspace,
                user=request.user
            )
            
            # Prepare order creation kwargs
            order_kwargs = {
                'customer_note': customer_note,
                'user': request.user
            }
            
            # Prefer freight_service_id over shipping_method over shipping_cost/tax
            if freight_service_id:
                try:
                    order_kwargs['freight_service_id'] = int(freight_service_id)
                except (ValueError, TypeError):
                    pass
            elif shipping_method:
                order_kwargs['shipping_method'] = shipping_method
            else:
                # Backward compatibility: convert shipping_cost and tax to Decimal if provided
                from decimal import Decimal
                if shipping_cost is not None:
                    try:
                        order_kwargs['shipping_cost'] = Decimal(str(shipping_cost))
                    except (ValueError, TypeError):
                        pass
                
                if tax is not None:
                    try:
                        order_kwargs['tax'] = Decimal(str(tax))
                    except (ValueError, TypeError):
                        pass
            
            order = order_service.create_order_from_cart(
                cart=cart,
                store=store,
                shipping_address=shipping_address,
                billing_address=billing_address,
                **order_kwargs
            )
            
            serializer = StorefrontOrderSerializer(order, context={'request': request})
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

    @action(
        detail=False,
        methods=['post'],
        authentication_classes=[],
        permission_classes=[AllowAny]
    )
    def guest_checkout(self, request):
        """
        Guest checkout - allows anonymous users to place orders using session cart.
        Expects:
        {
            "store": number,
            "shipping_address": {...},
            "billing_same_as_shipping": true/false,
            "billing_address": {...} (if not same),
            "customer_note": "...",
            "email": "...", "full_name": "...", "phone": "..."
        }
        """
        # If user is authenticated, delegate to regular checkout
        if request.user.is_authenticated:
            return self.checkout(request)

        # Ensure session exists
        if not request.session.session_key:
            request.session.create()

        cart = self._get_or_create_cart()

        if not cart.items.exists():
            return Response(
                {'detail': 'Cart is empty'},
                status=status.HTTP_400_BAD_REQUEST
            )

        store_id = request.data.get('store')
        shipping_data = request.data.get('shipping_address') or {}
        billing_same_as_shipping = request.data.get('billing_same_as_shipping', True)
        billing_data = request.data.get('billing_address') or {}
        customer_note = request.data.get('customer_note', '')
        freight_service_id = request.data.get('freight_service_id')  # Preferred
        shipping_method = request.data.get('shipping_method')  # Backward compatibility: 'standard' or 'express'
        shipping_cost = request.data.get('shipping_cost')  # Backward compatibility
        tax = request.data.get('tax')  # Backward compatibility

        email = request.data.get('email') or shipping_data.get('email')
        full_name = request.data.get('full_name') or shipping_data.get('full_name')
        phone = request.data.get('phone') or shipping_data.get('phone', '')

        if not store_id:
            return Response({'detail': 'store is required'}, status=status.HTTP_400_BAD_REQUEST)

        if not email or not full_name:
            return Response({'detail': 'email and full_name are required for guest checkout'}, status=status.HTTP_400_BAD_REQUEST)

        required_fields = ['address_line1', 'city', 'postal_code', 'country']
        for field in required_fields:
            if not shipping_data.get(field):
                return Response({'detail': f'Shipping address missing field: {field}'}, status=status.HTTP_400_BAD_REQUEST)

        # Create or get user by email
        user = User.objects.filter(email=email).first()
        if not user:
            username = email if email else f'guest_{uuid.uuid4().hex[:12]}'
            user = User.objects.create(username=username, email=email, first_name=full_name, is_active=True)
            user.set_unusable_password()
            user.save()
        else:
            # Update name if empty
            if not user.first_name and full_name:
                user.first_name = full_name
                user.save(update_fields=['first_name'])

        # Get workspace (with fallback to Site domain lookup)
        workspace = self._get_workspace(request)
        if not workspace:
            return Response(
                {'detail': 'No active workspace found. Please ensure domain is configured correctly.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get or create customer for workspace
        customer, _ = Customer.objects.get_or_create(
            user=user,
            workspace=workspace,
            defaults={'is_active': True}
        )

        try:
            store = Store.objects.get(id=store_id, workspace=workspace)
        except Store.DoesNotExist:
            return Response({'detail': 'Store not found'}, status=status.HTTP_404_NOT_FOUND)

        # Create shipping address
        shipping_address = Address.objects.create(
            workspace=workspace,
            content_object=customer,
            full_name=shipping_data.get('full_name') or full_name,
            phone=shipping_data.get('phone') or phone or '',
            email=shipping_data.get('email') or email or '',
            address_line1=shipping_data.get('address_line1'),
            address_line2=shipping_data.get('address_line2', ''),
            city=shipping_data.get('city'),
            state=shipping_data.get('state', ''),
            postal_code=shipping_data.get('postal_code'),
            country=(shipping_data.get('country') or '')[:2]  # Ensure max_length=2
        )

        billing_address = shipping_address
        if not billing_same_as_shipping:
            for field in required_fields:
                if not billing_data.get(field):
                    return Response({'detail': f'Billing address missing field: {field}'}, status=status.HTTP_400_BAD_REQUEST)
            billing_address = Address.objects.create(
                workspace=workspace,
                content_object=customer,
                full_name=billing_data.get('full_name') or full_name,
                phone=billing_data.get('phone') or phone or '',
                email=billing_data.get('email') or email or '',
                address_line1=billing_data.get('address_line1'),
                address_line2=billing_data.get('address_line2', ''),
                city=billing_data.get('city'),
                state=billing_data.get('state', ''),
                postal_code=billing_data.get('postal_code'),
                country=(billing_data.get('country') or '')[:2]
            )

        # Associate cart with customer
        cart.customer = customer
        cart.save(update_fields=['customer'])

        order_service = OrderService(
            workspace=workspace,
            user=user
        )

        # Prepare order creation kwargs
        order_kwargs = {
            'customer_note': customer_note
        }
        
        # Prefer freight_service_id over shipping_method over shipping_cost/tax
        if freight_service_id:
            try:
                order_kwargs['freight_service_id'] = int(freight_service_id)
            except (ValueError, TypeError):
                pass
        elif shipping_method:
            order_kwargs['shipping_method'] = shipping_method
        else:
            # Backward compatibility: convert shipping_cost and tax to Decimal if provided
            from decimal import Decimal
            if shipping_cost is not None:
                try:
                    order_kwargs['shipping_cost'] = Decimal(str(shipping_cost))
                except (ValueError, TypeError):
                    pass
            
            if tax is not None:
                try:
                    order_kwargs['tax'] = Decimal(str(tax))
                except (ValueError, TypeError):
                    pass

        try:
            order = order_service.create_order_from_cart(
                cart=cart,
                store=store,
                shipping_address=shipping_address,
                billing_address=billing_address,
                **order_kwargs
            )
            serializer = StorefrontOrderSerializer(order, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class StorefrontOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Storefront order ViewSet - customer's orders only"""
    serializer_class = StorefrontOrderSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get orders for current customer"""
        customer, _ = Customer.objects.get_or_create(
            user=self.request.user,
            workspace=self.request.workspace,
            defaults={'is_active': True}
        )
        
        queryset = Order.objects.filter(
            workspace=self.request.workspace,
            customer=customer
        ).select_related(
            'customer', 'customer__user', 'store', 'shipping_address', 'billing_address'
        ).prefetch_related('items')
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel order"""
        order = self.get_object()
        reason = request.data.get('reason', '')
        
        # Verify order belongs to customer
        customer, _ = Customer.objects.get_or_create(
            user=request.user,
            workspace=request.workspace,
            defaults={'is_active': True}
        )
        
        if order.customer != customer:
            raise PermissionDenied("Order does not belong to current customer")
        
        service = OrderService(
            workspace=request.workspace,
            user=request.user
        )
        
        order = service.cancel_order(order, reason)
        serializer = self.get_serializer(order)
        return Response(serializer.data)


class StorefrontPaymentViewSet(viewsets.GenericViewSet):
    """Storefront payment ViewSet"""
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def gateways(self, request):
        """Get available payment gateways for storefront. Use ?client=mp for mini-program."""
        from bfg.shop.serializers.storefront import StorefrontPaymentGatewaySerializer
        from bfg.finance.gateways.loader import gateway_supports_client
        
        gateways = list(PaymentGateway.objects.filter(
            workspace=request.workspace,
            is_active=True
        ).order_by('name'))
        client = (request.query_params.get('client') or '').strip().lower()
        if client:
            gateways = [g for g in gateways if gateway_supports_client(g.gateway_type, client)]
        
        serializer = StorefrontPaymentGatewaySerializer(gateways, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def intent(self, request):
        """Create payment intent"""
        serializer = PaymentIntentSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        order_id = serializer.validated_data['order_id']
        gateway_id = serializer.validated_data.get('gateway_id')
        payment_method_id = serializer.validated_data.get('payment_method_id')
        customer_id = serializer.validated_data.get('customer_id')
        save_card = serializer.validated_data.get('save_card', False)
        
        # Get order
        order = Order.objects.get(id=order_id, workspace=request.workspace)
        
        is_staff = getattr(request, 'is_staff_member', False) or request.user.is_superuser
        if is_staff:
            # Staff/admin can pay on behalf of the order customer
            if customer_id:
                customer = Customer.objects.filter(id=customer_id, workspace=request.workspace).first()
                if not customer:
                    raise ValidationError("Customer not found")
            else:
                customer = order.customer
            
            if order.customer != customer:
                raise ValidationError("Order does not belong to specified customer")
        else:
            # Regular customer flow
            customer, _ = Customer.objects.get_or_create(
                user=request.user,
                workspace=request.workspace,
                defaults={'is_active': True}
            )
            
            if order.customer != customer:
                raise PermissionDenied("Order does not belong to current customer")
        
        # Get gateway (use default if not specified)
        if gateway_id:
            gateway = PaymentGateway.objects.get(id=gateway_id, workspace=request.workspace)
        else:
            gateway = PaymentGateway.objects.filter(
                workspace=request.workspace,
                is_active=True
            ).first()
            
            if not gateway:
                return Response(
                    {'detail': 'No active payment gateway found'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Get currency from workspace settings or default
        default_currency_code = 'USD'  # Default fallback
        if hasattr(request.workspace, 'workspace_settings') and request.workspace.workspace_settings:
            default_currency_code = request.workspace.workspace_settings.default_currency or 'USD'
        
        # Get currency by code
        try:
            currency = Currency.objects.get(code=default_currency_code, is_active=True)
        except Currency.DoesNotExist:
            # Fallback to first active currency
            currency = Currency.objects.filter(is_active=True).first()
            if not currency:
                return Response(
                    {'detail': 'No active currency found. Please configure a currency first.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Get payment method if provided
        payment_method = None
        if payment_method_id:
            from bfg.finance.models import PaymentMethod
            try:
                payment_method = PaymentMethod.objects.get(
                    id=payment_method_id,
                    customer=customer
                )
            except PaymentMethod.DoesNotExist:
                return Response(
                    {'detail': 'Payment method not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Check for existing pending payment for this order (avoid duplicate payment records)
        existing_payment = Payment.objects.filter(
            order=order,
            customer=customer,
            status='pending'
        ).first()
        
        if existing_payment:
            # Reuse existing pending payment, update gateway if different
            payment = existing_payment
            if payment.gateway != gateway:
                payment.gateway = gateway
            if payment_method and payment.payment_method != payment_method:
                payment.payment_method = payment_method
            payment.save()
        else:
            # Create new payment using service
            payment_service = PaymentService(
                workspace=request.workspace,
                user=request.user
            )
            
            payment = payment_service.create_payment(
                customer=customer,
                amount=order.total,
                currency=currency,
                gateway=gateway,
                order=order,
                payment_method=payment_method
            )
        
        # Generate gateway payload (simplified - integrate with actual gateway)
        try:
            gateway_payload = self._generate_gateway_payload(payment, gateway, save_card=save_card)
        except Exception as e:
            from bfg.finance.exceptions import PaymentMethodInvalid
            if isinstance(e, PaymentMethodInvalid):
                return Response(
                    {'detail': e.message, 'code': getattr(e, 'code', 'payment_method_invalid')},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if isinstance(e, ValueError):
                return Response(
                    {'detail': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
            raise
        
        response_data = {
            'payment_id': payment.id,
            'payment_number': payment.payment_number,
            'amount': str(payment.amount),
            'currency': currency.code,
            'gateway_payload': gateway_payload,
            'status': payment.status
        }
        
        serializer = PaymentIntentResponseSerializer(data=response_data)
        serializer.is_valid(raise_exception=True)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def _generate_gateway_payload(self, payment, gateway, save_card=False):
        """Generate gateway-specific payload using plugin system"""
        from bfg.finance.gateways.loader import get_gateway_plugin
        
        plugin = get_gateway_plugin(gateway)
        if plugin:
            # Get payment method token if available
            payment_method_id = None
            if payment.payment_method:
                gateway_token = payment.payment_method.gateway_token
                # Validate Stripe PaymentMethod ID format (must start with 'pm_')
                if gateway_token and gateway_token.startswith('pm_'):
                    payment_method_id = gateway_token
                else:
                    # Skip invalid payment method IDs (may be old test data)
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"PaymentMethod {payment.payment_method.id} has invalid gateway_token format: "
                        f"{gateway_token}. Expected 'pm_...' format. PaymentIntent will be created without payment_method."
                    )
            
            # Create payment intent using plugin
            payment_intent = plugin.create_payment_intent(
                customer=payment.customer,
                amount=payment.amount,
                currency=payment.currency,
                payment_method_id=payment_method_id,
                order_id=payment.order.id if payment.order else None,
                metadata={
                    'payment_id': str(payment.id),
                    'payment_number': payment.payment_number,
                },
                save_card=save_card
            )
            
            # Store PaymentIntent ID in payment for later confirmation
            payment_intent_id = payment_intent.get('payment_intent_id') or payment_intent.get('id')
            if payment_intent_id:
                payment.gateway_transaction_id = payment_intent_id
                payment.save()
            
            return payment_intent
        
        # Default implementation for gateways without plugin
        return {
            'client_secret': f'client_secret_{payment.payment_number}',
            'payment_intent_id': payment.payment_number
        }
    
    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """Process payment (retry)"""
        try:
            payment = Payment.objects.get(id=pk, workspace=request.workspace)
        except Payment.DoesNotExist:
            raise NotFound("Payment not found")
        
        # Verify payment belongs to customer
        customer, _ = Customer.objects.get_or_create(
            user=request.user,
            workspace=request.workspace,
            defaults={'is_active': True}
        )
        
        if payment.customer != customer:
            raise PermissionDenied("Payment does not belong to current customer")
        
        payment_service = PaymentService(
            workspace=request.workspace,
            user=request.user
        )
        
        try:
            payment = payment_service.process_payment(payment)
            serializer = StorefrontPaymentSerializer(payment)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def callback(self, request, gateway=None):
        """Handle payment gateway callback (webhook)"""
        # This endpoint should be accessible without authentication
        # but should verify gateway signature
        
        from bfg.finance.gateways.loader import get_gateway_plugin
        from bfg.finance.services import PaymentService
        from bfg.common.models import Workspace
        import json
        import logging
        logger = logging.getLogger(__name__)
        
        # Parse webhook payload first to extract workspace_id
        try:
            if isinstance(request.body, bytes):
                payload = json.loads(request.body.decode('utf-8'))
            else:
                payload = request.data
        except (json.JSONDecodeError, AttributeError):
            payload = request.data
        
        # Extract workspace_id from Stripe metadata
        event_data = payload.get('data', {}).get('object', {})
        metadata = event_data.get('metadata', {})
        workspace_id = metadata.get('workspace_id')
        
        # Get workspace - try from metadata first, then from request
        workspace = None
        if workspace_id:
            try:
                workspace = Workspace.objects.get(id=workspace_id)
            except Workspace.DoesNotExist:
                logger.warning(f"Webhook: Workspace {workspace_id} not found in metadata")
        
        if not workspace:
            workspace = getattr(request, 'workspace', None)
        
        # Get gateway by gateway_type
        try:
            if workspace:
                payment_gateway = PaymentGateway.objects.get(
                    gateway_type=gateway,
                    workspace=workspace,
                    is_active=True
                )
            else:
                # Fallback: find any active gateway of this type
                payment_gateway = PaymentGateway.objects.filter(
                    gateway_type=gateway,
                    is_active=True
                ).first()
                if payment_gateway:
                    workspace = payment_gateway.workspace
        except PaymentGateway.DoesNotExist:
            return Response(
                {'detail': 'Payment gateway not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not payment_gateway:
            return Response(
                {'detail': 'Payment gateway not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Try to get gateway plugin
        plugin = None
        try:
            plugin = get_gateway_plugin(payment_gateway)
        except (ImportError, AttributeError):
            pass
        
        if plugin:
            # Get signature from header
            signature_header_name = getattr(plugin, 'signature_header_name', 'X-Gateway-Signature')
            signature = request.headers.get(signature_header_name) or request.headers.get('Stripe-Signature')
            
            if signature:
                if not plugin.verify_webhook(request.body, signature):
                    return Response(
                        {'detail': 'Invalid signature'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )
            
            # Extract event type
            event_type = payload.get('type') or payload.get('event_type') or 'payment.webhook'
            logger.info(f"Webhook: Processing {event_type} for workspace {workspace.id if workspace else 'None'}")
            
            # Handle webhook using plugin
            payment_service = PaymentService(
                workspace=workspace,
                user=None
            )
            
            result = plugin.handle_webhook(event_type, payload)
            
            # Process common payment updates
            payment_service.handle_webhook(payment_gateway, event_type, payload)
            
            return Response({'status': 'success', 'result': result}, status=status.HTTP_200_OK)
        else:
            return Response({'status': 'received'}, status=status.HTTP_200_OK)


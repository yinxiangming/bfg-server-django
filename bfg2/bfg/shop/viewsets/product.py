"""
Product-related ViewSets
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.utils.text import slugify
from django.db import transaction
from django.db.models import Sum
import logging

from bfg.core.permissions import IsWorkspaceStaff
from bfg.shop.models import ProductCategory, ProductTag, Product, ProductVariant, ProductReview, VariantInventory
from bfg.shop.serializers import (
    ProductCategorySerializer, ProductTagSerializer,
    ProductListSerializer, ProductDetailSerializer,
    ProductVariantSerializer, ProductReviewSerializer, VariantInventorySerializer
)
from bfg.shop.services import ProductService
from bfg.delivery.models import Warehouse
from bfg.shop.schemas import get_category_rules_form_schema


class ProductCategoryViewSet(viewsets.ModelViewSet):
    """Product category management ViewSet"""
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get categories for current workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        
        language = self.request.query_params.get('lang', 'en')
        queryset = ProductCategory.objects.filter(
            workspace=workspace,
            language=language
        ).select_related('parent').prefetch_related('children').order_by('order', 'name')
        
        # Filter active by default only for list actions
        # For retrieve/update/delete, show all to allow management of inactive categories
        if self.action == 'list':
            queryset = queryset.filter(is_active=True)
        
        # If tree=true, return only root categories (categories without parent)
        # The serializer will recursively include children
        if self.request.query_params.get('tree', '').lower() == 'true':
            queryset = queryset.filter(parent__isnull=True)
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """List categories, optionally as a tree structure"""
        response = super().list(request, *args, **kwargs)
        
        # If tree=true, return tree structure
        if request.query_params.get('tree', '').lower() == 'true':
            return response
        
        # Otherwise return flat list (for backward compatibility)
        return response
    
    def perform_create(self, serializer):
        """Create category with workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        serializer.save(workspace=workspace)

    @action(detail=False, methods=['get'])
    def rules_schema(self, request):
        """
        Return SchemaForm metadata for ProductCategory.rules editor.
        """
        return Response({
            'form_schema': get_category_rules_form_schema(),
        })


class ProductTagViewSet(viewsets.ModelViewSet):
    """Product tag management ViewSet"""
    serializer_class = ProductTagSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get tags for current workspace"""
        language = self.request.query_params.get('lang', 'en')
        return ProductTag.objects.filter(
            workspace=self.request.workspace,
            language=language
        ).order_by('name')


class ProductViewSet(viewsets.ModelViewSet):
    """
    Product management ViewSet
    
    Public can view active products, staff can manage all products
    """
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'list':
            return ProductListSerializer
        return ProductDetailSerializer
    
    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceStaff()]
    
    def get_queryset(self):
        """Get products based on permissions"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return Product.objects.none()
        queryset = Product.objects.filter(workspace=workspace).prefetch_related(
            'categories', 'tags', 'media_links__media', 'variants'
        )
        
        # Non-staff can only see active products
        if not getattr(self.request, 'is_staff_member', False):
            queryset = queryset.filter(is_active=True)
        
        # Filter by category
        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(categories__id=category_id)
        
        # Filter by tag
        tag_id = self.request.query_params.get('tag')
        if tag_id:
            queryset = queryset.filter(tags__id=tag_id)
        
        # Filter by language
        language = self.request.query_params.get('lang', 'en')
        queryset = queryset.filter(language=language)
        
        # Filter by featured
        featured = self.request.query_params.get('featured')
        if featured == 'true':
            queryset = queryset.filter(is_featured=True)
        
        # Search by name or SKU
        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(sku__icontains=search) |
                Q(variants__sku__icontains=search)
            ).distinct()
        
        return queryset.order_by('-is_featured', '-created_at')

    def create(self, request, *args, **kwargs):
        """Create product; require workspace; return 409 on duplicate (workspace, slug, language)."""
        from django.db.utils import IntegrityError
        if not getattr(request, 'workspace', None):
            return Response(
                {"detail": "No workspace. Send X-Workspace-ID header."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError as e:
            if 'Duplicate' in str(e) or 'unique' in str(e).lower() or 'UNIQUE' in str(e):
                return Response(
                    {"detail": "A product with this slug and language already exists in this workspace."},
                    status=status.HTTP_409_CONFLICT
                )
            raise
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """Create product using service"""
        category_ids = serializer.validated_data.pop('category_ids', None)
        tag_ids = serializer.validated_data.pop('tag_ids', None)
        tag_names = serializer.validated_data.pop('tag_names', None)
        
        product = serializer.save(workspace=self.request.workspace)
        
        if category_ids:
            categories = ProductCategory.objects.filter(
                id__in=category_ids,
                workspace=self.request.workspace
            )
            product.categories.set(categories)
        
        tags_to_add = []
        if tag_ids:
            existing_tags = ProductTag.objects.filter(
                id__in=tag_ids,
                workspace=self.request.workspace
            )
            tags_to_add.extend(list(existing_tags))
        
        if tag_names:
            language = serializer.validated_data.get('language') or self.request.query_params.get('lang', 'en')
            for tag_name in tag_names:
                tag_name = tag_name.strip()
                if not tag_name:
                    continue
                tag_slug = slugify(tag_name)
                tag, created = ProductTag.objects.get_or_create(
                    workspace=self.request.workspace,
                    slug=tag_slug,
                    language=language,
                    defaults={'name': tag_name}
                )
                if tag not in tags_to_add:
                    tags_to_add.append(tag)
        
        if tags_to_add:
            product.tags.set(tags_to_add)
    
    def perform_update(self, serializer):
        """Update product using service"""
        service = ProductService(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        category_ids = serializer.validated_data.pop('category_ids', None)
        tag_ids = serializer.validated_data.pop('tag_ids', None)
        tag_names = serializer.validated_data.pop('tag_names', None)
        
        if category_ids is not None:
            categories = ProductCategory.objects.filter(
                id__in=category_ids,
                workspace=self.request.workspace
            )
            serializer.validated_data['categories'] = categories
        
        if tag_ids is not None or tag_names is not None:
            tags_to_add = []
            if tag_ids:
                existing_tags = ProductTag.objects.filter(
                    id__in=tag_ids,
                    workspace=self.request.workspace
                )
                tags_to_add.extend(list(existing_tags))
            
            if tag_names:
                language = serializer.instance.language if hasattr(serializer.instance, 'language') else (
                    serializer.validated_data.get('language') or 
                    self.request.query_params.get('lang', 'en')
                )
                for tag_name in tag_names:
                    tag_name = tag_name.strip()
                    if not tag_name:
                        continue
                    tag_slug = slugify(tag_name)
                    tag, created = ProductTag.objects.get_or_create(
                        workspace=self.request.workspace,
                        slug=tag_slug,
                        language=language,
                        defaults={'name': tag_name}
                    )
                    if tag not in tags_to_add:
                        tags_to_add.append(tag)
            
            serializer.validated_data['tags'] = tags_to_add
        
        product = service.update_product(
            serializer.instance,
            **serializer.validated_data
        )
        serializer.instance = product
    
    @action(detail=True, methods=['get', 'put'], url_path='inventory', permission_classes=[IsAuthenticated, IsWorkspaceStaff])
    def inventory(self, request, pk=None):
        """
        Get or update variant inventories for a product
        
        GET: Returns all variant inventories for the product
        PUT: Updates variant inventories in bulk
        """
        product = self.get_object()
        
        if request.method == 'GET':
            # Get all variants for this product
            variants = ProductVariant.objects.filter(product=product)
            
            # Get all inventories for these variants
            inventories = VariantInventory.objects.filter(
                variant__in=variants
            ).select_related('variant', 'warehouse').order_by('variant__id', 'warehouse__id')
            
            serializer = VariantInventorySerializer(inventories, many=True)
            return Response(serializer.data)
        
        elif request.method == 'PUT':
            # Bulk update inventories
            inventories_data = request.data.get('inventories', [])
            
            if not isinstance(inventories_data, list):
                return Response(
                    {'error': 'inventories must be a list'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            with transaction.atomic():
                updated_inventories = []
                
                for inv_data in inventories_data:
                    variant_id = inv_data.get('variant')
                    warehouse_id = inv_data.get('warehouse')
                    quantity = inv_data.get('quantity', 0)
                    
                    if not variant_id or not warehouse_id:
                        continue
                    
                    # Verify variant belongs to this product
                    try:
                        variant = ProductVariant.objects.get(id=variant_id, product=product)
                    except ProductVariant.DoesNotExist:
                        continue
                    
                    # Verify warehouse exists and belongs to workspace
                    try:
                        warehouse = Warehouse.objects.get(id=warehouse_id, workspace=request.workspace)
                    except Warehouse.DoesNotExist:
                        continue
                    
                    # Get or create inventory record
                    inventory, created = VariantInventory.objects.get_or_create(
                        variant=variant,
                        warehouse=warehouse,
                        defaults={'quantity': 0, 'reserved': 0}
                    )
                    
                    # Update quantity
                    inventory.quantity = max(0, quantity)
                    inventory.save()
                    updated_inventories.append(inventory)
                
                # Update variant stock_quantity from inventories
                variants_to_update = set()
                for inventory in updated_inventories:
                    variants_to_update.add(inventory.variant)
                
                for variant in variants_to_update:
                    total_quantity = VariantInventory.objects.filter(
                        variant=variant
                    ).aggregate(total=Sum('quantity'))['total'] or 0
                    
                    variant.stock_quantity = total_quantity
                    variant.save()
                
                # Update product stock_quantity (sum of all variant stocks)
                product_total = ProductVariant.objects.filter(
                    product=product
                ).aggregate(total=Sum('stock_quantity'))['total'] or 0
                
                product.stock_quantity = product_total
                product.save()
            
            # Return updated inventories
            variants = ProductVariant.objects.filter(product=product)
            inventories = VariantInventory.objects.filter(
                variant__in=variants
            ).select_related('variant', 'warehouse').order_by('variant__id', 'warehouse__id')
            
            serializer = VariantInventorySerializer(inventories, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)


class ProductVariantViewSet(viewsets.ModelViewSet):
    """Product variant management ViewSet"""
    serializer_class = ProductVariantSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    logger = logging.getLogger(__name__)
    
    def get_queryset(self):
        """Get variants for current workspace"""
        queryset = ProductVariant.objects.filter(
            product__workspace=self.request.workspace
        ).select_related('product')
        
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
            
        return queryset
    
    def perform_create(self, serializer):
        """Create product variant"""
        serializer.save()

    def create(self, request, *args, **kwargs):
        """Log validation errors for variant creation to help debug 400 responses."""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            self.logger.warning("Variant create validation failed", extra={"errors": serializer.errors, "data": request.data})
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class ProductReviewViewSet(viewsets.ModelViewSet):
    """Product review ViewSet"""
    serializer_class = ProductReviewSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get reviews"""
        queryset = ProductReview.objects.filter(
            workspace=self.request.workspace
        ).select_related('product', 'customer')
        
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        if not getattr(self.request, 'is_staff_member', False):
            queryset = queryset.filter(is_approved=True)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create review"""
        from bfg.common.models import Customer
        
        customer = Customer.objects.get(
            workspace=self.request.workspace,
            user=self.request.user
        )
        
        serializer.save(
            workspace=self.request.workspace,
            customer=customer
        )


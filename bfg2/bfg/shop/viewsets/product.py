"""
Product-related ViewSets
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response


class PDFRenderer(BaseRenderer):
    media_type = 'application/pdf'
    format = 'pdf'
    charset = None
    render_style = 'binary'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data
from django.utils.text import slugify
from django.db import transaction
from django.db.models import Sum
import logging

from bfg.core.permissions import IsWorkspaceStaff
from bfg.shop.models import ProductCategory, ProductTag, Product, ProductVariant, ProductReview, VariantInventory
from bfg.shop.serializers import (
    ProductCategorySerializer, ProductTagSerializer,
    ProductListSerializer, ProductDetailSerializer,
    ProductPublicListSerializer, ProductPublicDetailSerializer,
    ProductVariantSerializer, ProductReviewSerializer, VariantInventorySerializer
)
from bfg.shop.services import ProductService, ensure_product_identifiers
from bfg.shop.services.product_identifier_service import generate_barcode_from_product_id
from bfg.delivery.models import Warehouse
from bfg.shop.schemas import get_category_rules_form_schema


class ProductCategoryViewSet(viewsets.ModelViewSet):
    """Product category management ViewSet"""
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """
        Categories for the current workspace.

        ``lang`` scopes the *list* — a category tree is per-language, so listing
        without it would interleave translations. A detail lookup is by primary
        key, which already names one row: narrowing it by language as well only
        turns "open this category" into a 404 whenever the row's language is not
        the one asked for. ``lang`` defaults to English, and the clients do not
        send it on detail requests, so a catalogue held in any other language
        could not be opened, edited or deleted from the admin at all.
        """
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")

        queryset = ProductCategory.objects.filter(
            workspace=workspace
        ).select_related('parent').prefetch_related('children').order_by('order', 'name')

        if self.action != 'list':
            return queryset

        # Fall back rather than return nothing: the admin asks with the language
        # of its own UI, which need not be the one the catalogue is written in.
        # A shop whose categories are all Chinese used to come back empty to an
        # English admin — and empty reads as "no categories", not "none in en".
        # The list carries a language column, so showing what does exist is
        # both honest and usable.
        language = self.request.query_params.get('lang', 'en')
        listed = queryset.filter(language=language)
        if not listed.exists():
            english = queryset.filter(language='en')
            listed = english if english.exists() else queryset

        # Staff endpoint: an inactive category stays listed, otherwise switching
        # one off in the admin would hide it and leave no way to switch it back
        # on. Callers wanting only the live tree ask for it explicitly.
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            listed = listed.filter(is_active=is_active.lower() in ('1', 'true', 'yes'))

        # If tree=true, return only root categories (categories without parent)
        if self.request.query_params.get('tree', '').lower() == 'true':
            listed = listed.filter(parent__isnull=True)

        return listed
    
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
        """Get tags for current workspace. See ProductCategoryViewSet: the
        language filter belongs to the list only, or a detail lookup 404s on
        every tag whose language is not the requested one."""
        queryset = ProductTag.objects.filter(workspace=self.request.workspace).order_by('name')
        if self.action != 'list':
            return queryset
        return queryset.filter(language=self.request.query_params.get('lang', 'en'))

    def perform_create(self, serializer):
        """Persist tag with workspace (FK required)."""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            from rest_framework.exceptions import NotFound
            raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
        serializer.save(workspace=workspace)


def _filter_products_queryset(queryset, request):
    """Shared filter helper used by both public and admin product viewsets."""
    category_id = request.query_params.get('category')
    if category_id:
        queryset = queryset.filter(categories__id=category_id)
    tag_id = request.query_params.get('tag')
    if tag_id:
        queryset = queryset.filter(tags__id=tag_id)
    lang_param = request.query_params.get('lang')
    if lang_param is not None:
        queryset = queryset.filter(language=lang_param)
    featured = request.query_params.get('featured')
    if featured == 'true':
        queryset = queryset.filter(is_featured=True)
    condition = request.query_params.get('condition')
    if condition:
        queryset = queryset.filter(condition=condition)
    search = request.query_params.get('search')
    if search:
        from django.db.models import Q
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(sku__icontains=search)
            | Q(barcode__icontains=search)
            | Q(variants__sku__icontains=search)
        ).distinct()
    return queryset.order_by('-is_featured', '-created_at')


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Storefront-facing product ViewSet — read-only, public.

    Returns only ``is_active=True`` products and exposes only public-safe
    fields via the ``ProductPublic*`` serializers (no ``cost``, ``barcode``,
    ``track_inventory``, ``low_stock_threshold``, ``finance_code``).

    Admin product management — including create / update / delete and the
    inventory / label / generate_identifiers actions — lives on the
    sibling :class:`AdminProductViewSet` at ``/api/v1/shop/admin/products/``.
    """
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductPublicListSerializer
        return ProductPublicDetailSerializer

    def get_queryset(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return Product.objects.none()
        queryset = Product.objects.filter(
            workspace=workspace, is_active=True,
        ).prefetch_related('categories', 'tags', 'media_links__media', 'variants')
        return _filter_products_queryset(queryset, self.request)


class AdminProductViewSet(viewsets.ModelViewSet):
    """
    Admin product management ViewSet — staff only.

    Returns the workspace's full product catalogue (including drafts and
    inactive items) via the full :class:`ProductDetailSerializer`, exposing
    ``cost``, ``barcode``, ``track_inventory``, ``low_stock_threshold`` and
    ``finance_code``. Hosts admin-only actions (``inventory``, ``label``,
    ``generate_identifiers``).
    """
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        return ProductDetailSerializer

    def get_queryset(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return Product.objects.none()
        queryset = Product.objects.filter(workspace=workspace).prefetch_related(
            'categories', 'tags', 'media_links__media', 'variants'
        )
        return _filter_products_queryset(queryset, self.request)

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
        ensure_product_identifiers(serializer.validated_data, workspace=self.request.workspace)
        barcode_prefix = serializer.validated_data.pop('_barcode_prefix', 'BC-')
        category_ids = serializer.validated_data.pop('category_ids', None)
        tag_ids = serializer.validated_data.pop('tag_ids', None)
        tag_names = serializer.validated_data.pop('tag_names', None)

        product = serializer.save(workspace=self.request.workspace)

        if not product.barcode:
            product.barcode = generate_barcode_from_product_id(product.pk, barcode_prefix)
            product.save(update_fields=['barcode'])
        
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

    @action(detail=True, methods=['get'], url_path='label',
            permission_classes=[IsAuthenticated, IsWorkspaceStaff],
            renderer_classes=[PDFRenderer])
    def label(self, request, pk=None):
        """Return a printable PDF label for the product (barcode + name + SKU)."""
        product = self.get_object()
        try:
            pdf_bytes = _generate_product_label_pdf(product)
        except Exception as exc:
            logger.exception("Failed to generate product label for product %s: %s", pk, exc)
            return Response({'detail': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        response = Response(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="product-{product.pk}-label.pdf"'
        return response

    @action(detail=True, methods=['get'], url_path='generate_identifiers',
            permission_classes=[IsAuthenticated, IsWorkspaceStaff])
    def generate_identifiers(self, request, pk=None):
        """Return freshly generated SKU and barcode values without saving them.

        Query params:
          - name: product name to use for SKU generation (defaults to current product name)
          - fields: comma-separated list of fields to regenerate, e.g. 'sku,barcode' (default: both)
        """
        from bfg.shop.services.product_identifier_service import (
            generate_sku, generate_barcode_from_product_id,
            get_workspace_identifier_prefixes,
        )
        product = self.get_object()
        name = request.query_params.get('name', product.name or '')
        fields_param = request.query_params.get('fields', 'sku,barcode')
        fields = {f.strip() for f in fields_param.split(',')}

        sku_prefix, barcode_prefix = get_workspace_identifier_prefixes(request.workspace)
        result = {}
        if 'sku' in fields:
            result['sku'] = generate_sku(sku_prefix, name)
        if 'barcode' in fields:
            result['barcode'] = generate_barcode_from_product_id(product.pk, barcode_prefix)
        return Response(result)


def _generate_product_label_pdf(product) -> bytes:
    """Generate a small label PDF using ReportLab with a Code128 barcode."""
    from io import BytesIO
    from reportlab.lib.pagesizes import mm
    from reportlab.lib.units import mm as mm_unit
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode import code128

    label_w = 80 * mm_unit
    label_h = 40 * mm_unit
    margin = 4 * mm_unit

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))

    barcode_value = str(product.barcode or product.sku or str(product.pk))

    # Draw barcode
    bar = code128.Code128(
        barcode_value,
        barWidth=1.2,
        barHeight=16 * mm_unit,
        humanReadable=True,
        fontSize=8,
    )
    bar_w = bar.width
    bar_x = (label_w - bar_w) / 2
    bar_y = margin + 6 * mm_unit
    bar.drawOn(c, bar_x, bar_y)

    # Product name (top area)
    name = (product.name or '')[:40]
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(label_w / 2, label_h - margin - 9, name)

    # SKU line
    sku_text = f"SKU: {product.sku}" if product.sku else ""
    if sku_text:
        c.setFont('Helvetica', 7)
        c.drawCentredString(label_w / 2, label_h - margin - 19, sku_text)

    c.save()
    return buf.getvalue()


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
    """Product review ViewSet for admin: list, filter, approve/reject, delete."""
    serializer_class = ProductReviewSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        """Get reviews with optional filters."""
        queryset = ProductReview.objects.filter(
            workspace=self.request.workspace
        ).select_related('product', 'customer', 'customer__user')
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        is_approved = self.request.query_params.get('is_approved')
        if is_approved is not None and is_approved != '':
            if is_approved.lower() in ('true', '1', 'yes'):
                queryset = queryset.filter(is_approved=True)
            elif is_approved.lower() in ('false', '0', 'no'):
                queryset = queryset.filter(is_approved=False)
        return queryset.order_by('-created_at')

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Approve a review (staff only)."""
        review = self.get_object()
        review.is_approved = True
        review.save(update_fields=['is_approved', 'updated_at'])
        serializer = self.get_serializer(review)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Reject a review (set is_approved=False)."""
        review = self.get_object()
        review.is_approved = False
        review.save(update_fields=['is_approved', 'updated_at'])
        serializer = self.get_serializer(review)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """Create review (admin create not typical; storefront uses store API)."""
        from bfg.common.models import Customer
        customer = Customer.objects.get(
            workspace=self.request.workspace,
            user=self.request.user
        )
        serializer.save(workspace=self.request.workspace, customer=customer)


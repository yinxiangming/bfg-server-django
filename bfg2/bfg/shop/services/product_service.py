"""
BFG Shop Module Services

Product management service
"""

from typing import Any, Optional, List
from decimal import Decimal
from django.db import transaction
from django.db.models import QuerySet
from django.utils.text import slugify
from bfg.core.services import BaseService
from bfg.shop.exceptions import ProductNotFound
from django.contrib.contenttypes.models import ContentType
from bfg.common.models import Media, MediaLink
from bfg.shop.models import (
    Product, ProductVariant, ProductCategory, ProductTag
)


class ProductService(BaseService):
    """
    Product management service
    
    Handles product creation, variants, images, and catalog management
    """
    
    @transaction.atomic
    def create_product(
        self,
        name: str,
        price: Decimal,
        **kwargs: Any
    ) -> Product:
        """
        Create new product
        
        Args:
            name: Product name
            price: Product price
            **kwargs: Additional product fields
            
        Returns:
            Product: Created product instance
        """
        # Generate slug if not provided
        slug = kwargs.get('slug')
        if not slug:
            slug = slugify(name)
            # Ensure uniqueness within workspace and language
            base_slug = slug
            counter = 1
            language = kwargs.get('language', 'en')
            while Product.objects.filter(
                workspace=self.workspace,
                slug=slug,
                language=language
            ).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
        
        # Create product
        product = Product.objects.create(
            workspace=self.workspace,
            name=name,
            slug=slug,
            sku=kwargs.get('sku', ''),
            product_type=kwargs.get('product_type', 'physical'),
            description=kwargs.get('description', ''),
            short_description=kwargs.get('short_description', ''),
            price=price,
            compare_price=kwargs.get('compare_price'),
            cost=kwargs.get('cost'),
            is_subscription=kwargs.get('is_subscription', False),
            subscription_plan=kwargs.get('subscription_plan'),
            track_inventory=kwargs.get('track_inventory', True),
            stock_quantity=kwargs.get('stock_quantity', 0),
            low_stock_threshold=kwargs.get('low_stock_threshold', 10),
            requires_shipping=kwargs.get('requires_shipping', True),
            weight=kwargs.get('weight'),
            meta_title=kwargs.get('meta_title', name),
            meta_description=kwargs.get('meta_description', ''),
            is_active=kwargs.get('is_active', True),
            is_featured=kwargs.get('is_featured', False),
            language=language,
        )
        
        # Add categories if provided
        if 'categories' in kwargs:
            product.categories.set(kwargs['categories'])
        
        # Add tags if provided
        if 'tags' in kwargs:
            product.tags.set(kwargs['tags'])
        
        # Emit product created event
        self.emit_event('product.created', {'product': product})
        
        return product
    
    def get_product_by_slug(self, slug: str, language: str = 'en') -> Product:
        """
        Get product by slug
        
        Args:
            slug: Product slug
            language: Language code
            
        Returns:
            Product: Product instance
            
        Raises:
            ProductNotFound: If product doesn't exist
        """
        try:
            product = Product.objects.prefetch_related(
                'categories', 'tags', 'media', 'variants'
            ).get(
                workspace=self.workspace,
                slug=slug,
                language=language
            )
            return product
        except Product.DoesNotExist:
            raise ProductNotFound(f"Product with slug '{slug}' not found")
    
    def update_product(self, product: Product, **kwargs: Any) -> Product:
        """
        Update product information
        
        Args:
            product: Product instance
            **kwargs: Fields to update
            
        Returns:
            Product: Updated product instance
        """
        self.validate_workspace_access(product)
        
        # Handle M2M relationships separately
        categories = kwargs.pop('categories', None)
        tags = kwargs.pop('tags', None)
        
        for key, value in kwargs.items():
            if hasattr(product, key) and key not in ['id', 'workspace', 'created_at']:
                setattr(product, key, value)
        
        product.save()
        
        # Update relationships if provided
        if categories is not None:
            product.categories.set(categories)
        
        if tags is not None:
            product.tags.set(tags)
        
        return product
    
    @transaction.atomic
    def create_variant(
        self,
        product: Product,
        sku: str,
        name: str,
        **kwargs: Any
    ) -> ProductVariant:
        """
        Create product variant
        
        Args:
            product: Product instance
            sku: Variant SKU
            name: Variant name
            **kwargs: Additional variant fields
            
        Returns:
            ProductVariant: Created variant instance
        """
        self.validate_workspace_access(product)
        
        variant = ProductVariant.objects.create(
            product=product,
            sku=sku,
            name=name,
            options=kwargs.get('options', {}),
            price=kwargs.get('price'),
            compare_price=kwargs.get('compare_price'),
            stock_quantity=kwargs.get('stock_quantity', 0),
            weight=kwargs.get('weight'),
            is_active=kwargs.get('is_active', True),
            order=kwargs.get('order', 100),
        )
        
        return variant
    
    @transaction.atomic
    def add_product_media(
        self,
        product: Product,
        file: Any,
        **kwargs: Any
    ) -> MediaLink:
        """
        Add media to product using MediaLink
        
        Args:
            product: Product instance
            file: Media file
            **kwargs: Additional media fields
            
        Returns:
            MediaLink: Created media link instance
        """
        self.validate_workspace_access(product)
        
        # Create Media object
        folder = kwargs.get('folder', 'products').strip()
        media = Media(
            workspace=self.workspace,
            file=file,
            external_url=kwargs.get('external_url', ''),
            media_type=kwargs.get('media_type', 'image'),
            alt_text=kwargs.get('alt_text', ''),
            uploaded_by=self.user,
        )
        if folder:
            media._upload_folder = folder
        media.save()
        
        # Create MediaLink
        media_link = MediaLink.objects.create(
            media=media,
            content_object=product,
            position=kwargs.get('position', 100),
            description=kwargs.get('description', '')
        )
        
        return media_link
    
    def get_active_products(
        self,
        category: Optional[ProductCategory] = None,
        tag: Optional[ProductTag] = None,
        language: str = 'en',
        limit: Optional[int] = None
    ) -> QuerySet[Product]:
        """
        Get active products with optional filters
        
        Args:
            category: Filter by category
            tag: Filter by tag
            language: Language code
            limit: Maximum number of products
            
        Returns:
            QuerySet: Active products
        """
        queryset = Product.objects.filter(
            workspace=self.workspace,
            is_active=True,
            language=language
        ).prefetch_related('categories', 'tags', 'media_links__media')
        
        if category:
            queryset = queryset.filter(categories=category)
        
        if tag:
            queryset = queryset.filter(tags=tag)
        
        if limit:
            queryset = queryset[:limit]
        
        return queryset.order_by('-is_featured', '-created_at')
    
    def deactivate_product(self, product: Product) -> Product:
        """
        Deactivate product
        
        Args:
            product: Product instance
            
        Returns:
            Product: Updated product instance
        """
        self.validate_workspace_access(product)
        
        product.is_active = False
        product.save()
        
        return product

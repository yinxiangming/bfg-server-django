"""
BFG Shop Module Cache Services

Cache services for shop module performance optimization
"""

from typing import Any, Optional, List
from decimal import Decimal
from django.core.cache import cache
from bfg.core.cache import CacheMixin
from bfg.shop.models import Product, Cart


class ProductCacheService(CacheMixin):
    """
    Cache service for individual products
    
    Reduces database queries for frequently accessed products
    """
    
    cache_prefix = 'product'
    cache_timeout = 3600  # 1 hour
    
    @classmethod
    def get_product(cls, product_id: int, workspace_id: int) -> Optional[Product]:
        """
        Get product from cache or database
        
        Args:
            product_id: Product ID
            workspace_id: Workspace ID
            
        Returns:
            Product or None: Product instance
        """
        cache_key = cls.get_cache_key(f'{workspace_id}:{product_id}')
        
        # Try cache first
        product = cache.get(cache_key)
        if product is not None:
            return product
        
        # Query database
        try:
            product = Product.objects.with_related().get(
                id=product_id,
                workspace_id=workspace_id
            )
            
            # Cache the result
            cache.set(cache_key, product, cls.cache_timeout)
            return product
        except Product.DoesNotExist:
            return None
    
    @classmethod
    def invalidate_product(cls, product_id: int, workspace_id: int) -> None:
        """
        Invalidate cached product
        
        Args:
            product_id: Product ID
            workspace_id: Workspace ID
        """
        cache_key = cls.get_cache_key(f'{workspace_id}:{product_id}')
        cache.delete(cache_key)
    
    @classmethod
    def get_product_by_slug(cls, slug: str, workspace_id: int, language: str = 'en') -> Optional[Product]:
        """
        Get product by slug from cache or database
        
        Args:
            slug: Product slug
            workspace_id: Workspace ID
            language: Language code
            
        Returns:
            Product or None: Product instance
        """
        cache_key = cls.get_cache_key(f'{workspace_id}:{language}:{slug}')
        
        # Try cache first
        product = cache.get(cache_key)
        if product is not None:
            return product
        
        # Query database
        try:
            product = Product.objects.with_related().get(
                slug=slug,
                workspace_id=workspace_id,
                language=language
            )
            
            # Cache the result
            cache.set(cache_key, product, cls.cache_timeout)
            return product
        except Product.DoesNotExist:
            return None


class ProductListCacheService(CacheMixin):
    """
    Cache service for product lists
    
    Caches filtered product listings
    """
    
    cache_prefix = 'product_list'
    cache_timeout = 1800  # 30 minutes
    
    @classmethod
    def get_featured_products(
        cls,
        workspace_id: int,
        language: str = 'en',
        limit: int = 10
    ) -> Optional[List[Product]]:
        """
        Get featured products from cache
        
        Args:
            workspace_id: Workspace ID
            language: Language code
            limit: Maximum number of products
            
        Returns:
            List of products or None
        """
        cache_key = cls.get_cache_key(f'featured:{workspace_id}:{language}:{limit}')
        
        # Try cache first
        products = cache.get(cache_key)
        if products is not None:
            return products
        
        # Query database
        products = list(Product.objects.filter(
            workspace_id=workspace_id,
            language=language,
            is_active=True,
            is_featured=True
        ).with_related()[:limit])
        
        # Cache the result
        cache.set(cache_key, products, cls.cache_timeout)
        return products
    
    @classmethod
    def get_category_products(
        cls,
        workspace_id: int,
        category_id: int,
        language: str = 'en',
        page: int = 1,
        page_size: int = 20
    ) -> Optional[List[Product]]:
        """
        Get products in category from cache
        
        Args:
            workspace_id: Workspace ID
            category_id: Category ID
            language: Language code
            page: Page number
            page_size: Items per page
            
        Returns:
            List of products or None
        """
        cache_key = cls.get_cache_key(
            f'category:{workspace_id}:{category_id}:{language}:{page}:{page_size}'
        )
        
        # Try cache first
        products = cache.get(cache_key)
        if products is not None:
            return products
        
        # Query database
        offset = (page - 1) * page_size
        products = list(Product.objects.filter(
            workspace_id=workspace_id,
            categories__id=category_id,
            language=language,
            is_active=True
        ).with_related()[offset:offset + page_size])
        
        # Cache the result
        cache.set(cache_key, products, cls.cache_timeout)
        return products
    
    @classmethod
    def invalidate_workspace_lists(cls, workspace_id: int) -> None:
        """
        Invalidate all product list caches for workspace
        
        Args:
            workspace_id: Workspace ID
        """
        # Clear all caches with this workspace prefix
        pattern = cls.get_cache_key(f'*:{workspace_id}:*')
        cls.delete_pattern(pattern)


class CartCacheService(CacheMixin):
    """
    Cache service for shopping carts
    
    Caches cart state for quick access
    """
    
    cache_prefix = 'cart'
    cache_timeout = 3600  # 1 hour
    
    @classmethod
    def get_cart_summary(cls, cart_id: int) -> Optional[dict]:
        """
        Get cart summary from cache
        
        Args:
            cart_id: Cart ID
            
        Returns:
            Dict with cart summary or None
        """
        cache_key = cls.get_cache_key(f'summary:{cart_id}')
        
        summary = cache.get(cache_key)
        return summary
    
    @classmethod
    def set_cart_summary(cls, cart_id: int, summary: dict) -> None:
        """
        Cache cart summary
        
        Args:
            cart_id: Cart ID
            summary: Cart summary dict
        """
        cache_key = cls.get_cache_key(f'summary:{cart_id}')
        cache.set(cache_key, summary, cls.cache_timeout)
    
    @classmethod
    def invalidate_cart(cls, cart_id: int) -> None:
        """
        Invalidate cached cart
        
        Args:
            cart_id: Cart ID
        """
        cache_key = cls.get_cache_key(f'summary:{cart_id}')
        cache.delete(cache_key)
    
    @classmethod
    def get_cart_count(cls, cart_id: int) -> Optional[int]:
        """
        Get cart item count from cache
        
        Args:
            cart_id: Cart ID
            
        Returns:
            Item count or None
        """
        cache_key = cls.get_cache_key(f'count:{cart_id}')
        return cache.get(cache_key)
    
    @classmethod
    def set_cart_count(cls, cart_id: int, count: int) -> None:
        """
        Cache cart item count
        
        Args:
            cart_id: Cart ID
            count: Item count
        """
        cache_key = cls.get_cache_key(f'count:{cart_id}')
        cache.set(cache_key, count, cls.cache_timeout)

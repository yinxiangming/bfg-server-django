"""
BFG Shop Module Managers

Custom managers for shop models
"""

from typing import Optional
from django.db import models
from django.db.models import QuerySet, Prefetch, Count, Avg


class ProductManager(models.Manager):
    """
    Custom manager for Product model with query optimizations
    """
    
    def active(self) -> QuerySet:
        """Get active products"""
        return self.filter(is_active=True)
    
    def featured(self) -> QuerySet:
        """Get featured products"""
        return self.filter(is_active=True, is_featured=True)
    
    def with_related(self) -> QuerySet:
        """
        Prefetch related data for product listing
        Optimizes queries for list views
        """
        return self.select_related(
            'subscription_plan'
        ).prefetch_related(
            'categories',
            'tags',
            'media_links__media',
            'variants'
        )
    
    def with_stats(self) -> QuerySet:
        """
        Annotate products with review stats
        """
        return self.annotate(
            review_count=Count('reviews', filter=models.Q(reviews__is_approved=True)),
            avg_rating=Avg('reviews__rating', filter=models.Q(reviews__is_approved=True))
        )
    
    def by_category(self, category_id: int) -> QuerySet:
        """
        Get products in category (including subcategories)
        
        Args:
            category_id: Category ID
            
        Returns:
            QuerySet: Filtered products
        """
        return self.filter(
            categories__id=category_id,
            is_active=True
        )
    
    def search(self, query: str) -> QuerySet:
        """
        Search products by name and description
        
        Args:
            query: Search query
            
        Returns:
            QuerySet: Matching products
        """
        return self.filter(
            models.Q(name__icontains=query) |
            models.Q(description__icontains=query) |
            models.Q(sku__icontains=query),
            is_active=True
        )


class CartManager(models.Manager):
    """
    Custom manager for Cart model
    """
    
    def with_items(self) -> QuerySet:
        """Prefetch cart items with products"""
        return self.prefetch_related(
            Prefetch(
                'items',
                queryset=models.get_model('shop', 'CartItem').objects.select_related(
                    'product', 'variant'
                )
            )
        )
    
    def active_carts(self) -> QuerySet:
        """Get carts with items (not empty)"""
        return self.annotate(
            item_count=Count('items')
        ).filter(item_count__gt=0)
    
    def abandoned_carts(self, days: int = 7) -> QuerySet:
        """
        Get abandoned carts (not updated in X days)
        
        Args:
            days: Number of days to consider as abandoned
            
        Returns:
            QuerySet: Abandoned carts
        """
        from django.utils import timezone
        from datetime import timedelta
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        return self.active_carts().filter(
            updated_at__lt=cutoff_date
        )


class InventoryManager(models.Manager):
    """
    Custom manager for VariantInventory model
    """
    
    def low_stock(self, threshold: Optional[int] = None) -> QuerySet:
        """
        Get inventory records with low stock
        
        Args:
            threshold: Stock threshold (uses variant's low_stock_threshold if not provided)
            
        Returns:
            QuerySet: Low stock inventory records
        """
        if threshold:
            return self.filter(
                quantity__lte=threshold
            ).select_related('variant', 'warehouse')
        else:
            # Use product's low_stock_threshold
            return self.filter(
                quantity__lte=models.F('variant__product__low_stock_threshold')
            ).select_related('variant', 'warehouse')
    
    def out_of_stock(self) -> QuerySet:
        """Get out of stock inventory records"""
        return self.filter(
            quantity__lte=models.F('reserved')
        ).select_related('variant', 'warehouse')
    
    def by_warehouse(self, warehouse_id: int) -> QuerySet:
        """
        Get inventory for specific warehouse
        
        Args:
            warehouse_id: Warehouse ID
            
        Returns:
            QuerySet: Warehouse inventory
        """
        return self.filter(
            warehouse_id=warehouse_id
        ).select_related('variant__product')

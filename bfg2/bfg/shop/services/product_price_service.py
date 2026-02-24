# -*- coding: utf-8 -*-
"""
Product Price Service
Handles product pricing logic including effective price calculation and price scheduling.
"""

from decimal import Decimal
from typing import Optional
from django.utils import timezone
from bfg.core.services import BaseService


class ProductPriceService(BaseService):
    """Service for managing product prices and price changes."""
    
    def get_effective_price(self, product, at_time: Optional[timezone.datetime] = None) -> Decimal:
        """
        Get effective price for a product at specified time.
        Checks price history for scheduled price changes.
        
        Args:
            product: Product instance
            at_time: Datetime to check price at. Defaults to now.
        
        Returns:
            Decimal: Effective price at specified time
        
        Raises:
            ValueError: If product is not active
        """
        if not product.is_active:
            raise ValueError(f"Product '{product.name}' (ID: {product.id}) is not active")
        
        if at_time is None:
            at_time = timezone.now()
        
        # Import here to avoid circular import
        from bfg.shop.models import ProductPriceHistory
        
        # Find most recent active price change before or at specified time
        price_change = ProductPriceHistory.objects.filter(
            product=product,
            effective_at__lte=at_time,
            status='active'
        ).order_by('-effective_at').first()
        
        if price_change:
            return price_change.new_price
        
        # No price history, use current price
        return product.price
    
    def schedule_price_change(
        self,
        product,
        new_price: Decimal,
        effective_at: timezone.datetime,
        changed_by,
        reason: str = ''
    ):
        """
        Schedule a price change for a product.
        
        Args:
            product: Product instance
            new_price: New price (Decimal)
            effective_at: When to apply the price change
            changed_by: User making the change
            reason: Optional reason for the change
        
        Returns:
            ProductPriceHistory: Created price history record
        """
        from bfg.shop.models import ProductPriceHistory
        
        # Get current effective price
        current_price = self.get_effective_price(product)
        
        # Determine initial status
        now = timezone.now()
        if effective_at <= now:
            status = 'active'
            # Apply immediately
            product.price = new_price
            product.save(update_fields=['price', 'updated_at'])
        else:
            status = 'pending'
        
        # Create price history record
        return ProductPriceHistory.objects.create(
            workspace=product.workspace,
            product=product,
            old_price=current_price,
            new_price=new_price,
            effective_at=effective_at,
            changed_by=changed_by,
            reason=reason,
            status=status
        )
    
    def activate_pending_price_changes(self):
        """
        Activate all pending price changes that have reached their effective time.
        This is typically called by a Celery task.
        
        Returns:
            dict: Summary of activation results
        """
        from bfg.shop.models import ProductPriceHistory
        
        now = timezone.now()
        
        # Find all pending price changes that should now be active
        pending_changes = ProductPriceHistory.objects.filter(
            effective_at__lte=now,
            status='pending'
        ).select_related('product')
        
        activated_count = 0
        failed_count = 0
        errors = []
        
        for change in pending_changes:
            try:
                # Update product price
                change.product.price = change.new_price
                change.product.save(update_fields=['price', 'updated_at'])
                
                # Mark change as active
                change.status = 'active'
                change.save(update_fields=['status'])
                
                activated_count += 1
            except Exception as e:
                failed_count += 1
                errors.append({
                    'change_id': change.id,
                    'product_id': change.product.id,
                    'error': str(e)
                })
        
        return {
            'activated_count': activated_count,
            'failed_count': failed_count,
            'errors': errors,
            'timestamp': now.isoformat()
        }

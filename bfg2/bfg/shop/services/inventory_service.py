"""
BFG Shop Module Services

Inventory management service
"""

from typing import Any, Optional, List
from decimal import Decimal
from django.db import transaction
from django.db.models import F, QuerySet, Sum
from bfg.core.services import BaseService
from bfg.shop.exceptions import InsufficientStock
from bfg.shop.models import Product, ProductVariant, VariantInventory
from bfg.delivery.models import Warehouse


class InventoryService(BaseService):
    """
    Inventory management service
    
    Handles stock tracking, reservation, and allocation across warehouses
    """
    
    def get_variant_inventory(
        self,
        variant: ProductVariant,
        warehouse: Warehouse
    ) -> VariantInventory:
        """
        Get or create inventory record for variant in warehouse
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            
        Returns:
            VariantInventory: Inventory record
        """
        inventory, created = VariantInventory.objects.get_or_create(
            variant=variant,
            warehouse=warehouse,
            defaults={'quantity': 0, 'reserved': 0}
        )
        
        return inventory
    
    @transaction.atomic
    def adjust_stock(
        self,
        variant: ProductVariant,
        warehouse: Warehouse,
        quantity_change: int,
        reason: str = ''
    ) -> VariantInventory:
        """
        Adjust stock quantity (positive or negative)
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            quantity_change: Change in quantity (+ for increase, - for decrease)
            reason: Reason for adjustment
            
        Returns:
            VariantInventory: Updated inventory record
        """
        inventory = self.get_variant_inventory(variant, warehouse)
        
        # Update quantity
        inventory.quantity = F('quantity') + quantity_change
        inventory.save()
        inventory.refresh_from_db()
        
        # Also update variant's total stock_quantity
        total_quantity = VariantInventory.objects.filter(
            variant=variant
        ).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        variant.stock_quantity = total_quantity
        variant.save()
        
        return inventory
    
    @transaction.atomic
    def reserve_stock(
        self,
        variant: ProductVariant,
        warehouse: Warehouse,
        quantity: int
    ) -> VariantInventory:
        """
        Reserve stock for an order
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            quantity: Quantity to reserve
            
        Returns:
            VariantInventory: Updated inventory record
            
        Raises:
            InsufficientStock: If not enough available stock
        """
        inventory = self.get_variant_inventory(variant, warehouse)
        
        # Check available quantity
        if inventory.available < quantity:
            raise InsufficientStock(
                f"Only {inventory.available} units available in {warehouse.name}"
            )
        
        # Reserve stock
        inventory.reserved = F('reserved') + quantity
        inventory.save()
        inventory.refresh_from_db()
        
        return inventory
    
    @transaction.atomic
    def release_reservation(
        self,
        variant: ProductVariant,
        warehouse: Warehouse,
        quantity: int
    ) -> VariantInventory:
        """
        Release reserved stock (e.g., when order is cancelled)
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            quantity: Quantity to release
            
        Returns:
            VariantInventory: Updated inventory record
        """
        inventory = self.get_variant_inventory(variant, warehouse)
        
        # Release reservation
        new_reserved = max(0, inventory.reserved - quantity)
        inventory.reserved = new_reserved
        inventory.save()
        
        return inventory
    
    @transaction.atomic
    def fulfill_reservation(
        self,
        variant: ProductVariant,
        warehouse: Warehouse,
        quantity: int
    ) -> VariantInventory:
        """
        Fulfill a reservation (deduct from both quantity and reserved)
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            quantity: Quantity to fulfill
            
        Returns:
            VariantInventory: Updated inventory record
        """
        inventory = self.get_variant_inventory(variant, warehouse)
        
        # Deduct from both quantity and reserved
        inventory.quantity = F('quantity') - quantity
        inventory.reserved = F('reserved') - quantity
        inventory.save()
        inventory.refresh_from_db()
        
        # Update variant's total stock_quantity
        from django.db.models import Sum
        total_quantity = VariantInventory.objects.filter(
            variant=variant
        ).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        variant.stock_quantity = total_quantity
        variant.save()
        
        return inventory
    
    def get_available_warehouses(
        self,
        variant: ProductVariant,
        min_quantity: int = 1
    ) -> QuerySet[VariantInventory]:
        """
        Get warehouses with available stock for variant
        
        Args:
            variant: ProductVariant instance
            min_quantity: Minimum available quantity required
            
        Returns:
            QuerySet: VariantInventory records with sufficient stock
        """
        from django.db.models import F
        
        return VariantInventory.objects.filter(
            variant=variant,
            quantity__gte=F('reserved') + min_quantity
        ).select_related('warehouse')
    
    def allocate_stock(
        self,
        variant: ProductVariant,
        required_quantity: int
    ) -> List[tuple[Warehouse, int]]:
        """
        Allocate stock across warehouses (simple FIFO strategy)
        
        Args:
            variant: ProductVariant instance
            required_quantity: Total quantity needed
            
        Returns:
            List of (Warehouse, quantity) tuples
            
        Raises:
            InsufficientStock: If total available stock is insufficient
        """
        available_inventories = self.get_available_warehouses(
            variant,
            min_quantity=1
        ).order_by('-quantity')  # Prefer warehouses with more stock
        
        # Calculate total available
        from django.db.models import Sum, F
        total_available = available_inventories.aggregate(
            total=Sum(F('quantity') - F('reserved'))
        )['total'] or 0
        
        if total_available < required_quantity:
            raise InsufficientStock(
                f"Only {total_available} units available across all warehouses"
            )
        
        # Allocate stock
        allocations = []
        remaining = required_quantity
        
        for inventory in available_inventories:
            if remaining <= 0:
                break
            
            available = inventory.quantity - inventory.reserved
            allocated = min(available, remaining)
            
            allocations.append((inventory.warehouse, allocated))
            remaining -= allocated
        
        return allocations

"""
Optional Batch Management Service for BFG Shop module.

Enable this feature by setting in workspace settings:
    settings['features']['batch_management'] = True

Or in Django settings:
    BFG2_SETTINGS = {
        'ENABLE_BATCH_MANAGEMENT': True,
    }
"""

from typing import Any, Optional, List, Tuple
from datetime import date, timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.conf import settings

from bfg.core.services import BaseService
from bfg.shop.exceptions import InsufficientStock


# Feature flag check
def is_batch_management_enabled(workspace=None) -> bool:
    """Check if batch management is enabled"""
    # Check Django settings
    bfg2_settings = getattr(settings, 'BFG2_SETTINGS', {})
    if bfg2_settings.get('ENABLE_BATCH_MANAGEMENT'):
        return True
    
    # Check workspace settings
    if workspace and isinstance(workspace.settings, dict):
        features = workspace.settings.get('features', {})
        return features.get('batch_management', False)
    
    return False


class BatchService(BaseService):
    """
    Batch management service
    
    Handles batch/lot tracking, FIFO allocation, and expiry management
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Only import models if feature is enabled
        if not is_batch_management_enabled(self.workspace):
            raise RuntimeError(
                "Batch management is not enabled. "
                "Enable it in workspace settings: features.batch_management = True"
            )
        
        # Import models dynamically
        from bfg.shop.batch_models import ProductBatch, BatchMovement
        self.ProductBatch = ProductBatch
        self.BatchMovement = BatchMovement
    
    @transaction.atomic
    def create_batch(
        self,
        variant: 'ProductVariant',
        warehouse: 'Warehouse',
        batch_number: str,
        quantity: int,
        manufactured_date: date,
        expiry_date: Optional[date] = None,
        **kwargs: Any
    ) -> 'ProductBatch':
        """
        Create new batch
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            batch_number: Unique batch number
            quantity: Initial quantity
            manufactured_date: Manufacturing date
            expiry_date: Expiry date (optional)
            **kwargs: purchase_price, notes, etc.
            
        Returns:
            ProductBatch: Created batch instance
        """
        batch = self.ProductBatch.objects.create(
            workspace=self.workspace,
            variant=variant,
            warehouse=warehouse,
            batch_number=batch_number,
            quantity=quantity,
            manufactured_date=manufactured_date,
            expiry_date=expiry_date,
            purchase_price=kwargs.get('purchase_price'),
            notes=kwargs.get('notes', ''),
        )
        
        # Record initial stock movement
        self.BatchMovement.objects.create(
            batch=batch,
            movement_type='in',
            quantity=quantity,
            reason='Initial stock',
            performed_by=self.user,
        )
        
        # Emit event
        self.emit_event('batch.created', {'batch': batch})
        
        return batch
    
    def allocate_stock_fifo(
        self,
        variant: 'ProductVariant',
        warehouse: 'Warehouse',
        required_quantity: int
    ) -> List[Tuple['ProductBatch', int]]:
        """
        Allocate stock using FIFO (First-In-First-Out) strategy
        
        Prioritizes batches by:
        1. Nearest expiry date
        2. Earliest manufacturing date
        
        Args:
            variant: ProductVariant instance
            warehouse: Warehouse instance
            required_quantity: Quantity needed
            
        Returns:
            List of (batch, quantity) tuples
            
        Raises:
            InsufficientStock: If not enough stock available
        """
        allocations = []
        remaining = required_quantity
        
        # Get available batches (FIFO order)
        batches = self.ProductBatch.objects.filter(
            workspace=self.workspace,
            variant=variant,
            warehouse=warehouse,
            quality_status='normal'
        ).exclude(
            expiry_date__lt=timezone.now().date()  # Exclude expired
        ).order_by('expiry_date', 'manufactured_date')
        
        for batch in batches:
            if remaining <= 0:
                break
            
            available = batch.available
            if available <= 0:
                continue
            
            allocated = min(available, remaining)
            allocations.append((batch, allocated))
            remaining -= allocated
        
        if remaining > 0:
            raise InsufficientStock(
                f"Only {required_quantity - remaining} units available "
                f"(needed {required_quantity})"
            )
        
        return allocations
    
    @transaction.atomic
    def reserve_batches(
        self,
        allocations: List[Tuple['ProductBatch', int]],
        order: 'Order'
    ) -> None:
        """
        Reserve batch stock for an order
        
        Args:
            allocations: List of (batch, quantity) tuples
            order: Order instance
        """
        for batch, quantity in allocations:
            batch.reserved += quantity
            batch.save()
            
            # Record reservation
            self.BatchMovement.objects.create(
                batch=batch,
                movement_type='out',
                quantity=-quantity,
                order=order,
                reason=f'Reserved for order {order.order_number}',
                performed_by=self.user,
            )
    
    def get_expiring_batches(
        self,
        days_threshold: int = 30
    ) -> QuerySet['ProductBatch']:
        """
        Get batches expiring within threshold
        
        Args:
            days_threshold: Number of days
            
        Returns:
            QuerySet: Expiring batches
        """
        cutoff_date = timezone.now().date() + timedelta(days=days_threshold)
        
        return self.ProductBatch.objects.filter(
            workspace=self.workspace,
            expiry_date__lte=cutoff_date,
            expiry_date__gte=timezone.now().date(),
            quantity__gt=0,
            quality_status='normal'
        ).select_related('variant__product', 'warehouse')
    
    def update_batch_status(self) -> dict:
        """
        Update batch quality status based on expiry dates
        
        Should be run daily via cron/celery
        
        Returns:
            dict: Summary of updates
        """
        today = timezone.now().date()
        warning_date = today + timedelta(days=30)
        
        # Mark near expiry
        near_expiry = self.ProductBatch.objects.filter(
            workspace=self.workspace,
            expiry_date__lte=warning_date,
            expiry_date__gt=today,
            quality_status='normal'
        ).update(quality_status='warning')
        
        # Mark expired
        expired = self.ProductBatch.objects.filter(
            workspace=self.workspace,
            expiry_date__lt=today,
            quality_status__in=['normal', 'warning']
        ).update(quality_status='expired')
        
        return {
            'near_expiry': near_expiry,
            'expired': expired,
        }


class ExpiryNotificationService(BaseService):
    """
    Expiry notification service
    
    Sends alerts for expiring batches
    """
    
    def send_expiry_warnings(self, days_threshold: int = 30) -> int:
        """
        Send expiry warning notifications
        
        Args:
            days_threshold: Days threshold for warning
            
        Returns:
            int: Number of notifications sent
        """
        if not is_batch_management_enabled(self.workspace):
            return 0
        
        batch_service = BatchService(workspace=self.workspace, user=self.user)
        expiring_batches = batch_service.get_expiring_batches(days_threshold)
        
        if not expiring_batches.exists():
            return 0
        
        # Group by warehouse
        from collections import defaultdict
        warehouse_batches = defaultdict(list)
        
        for batch in expiring_batches:
            warehouse_batches[batch.warehouse].append(batch)
        
        # Send notifications
        from bfg.inbox.services import MessageService
        message_service = MessageService(workspace=self.workspace, user=self.user)
        
        notifications_sent = 0
        
        for warehouse, batches in warehouse_batches.items():
            # Get warehouse managers (simplified - adjust based on your permission model)
            from bfg.common.models import StaffMember
            managers = StaffMember.objects.filter(
                workspace=self.workspace,
                # Add warehouse-specific filtering
            )
            
            if not managers:
                continue
            
            # Build message
            batch_list = '\n'.join([
                f"• {b.variant.product.name} - Batch {b.batch_number}\n"
                f"  Expires: {b.expiry_date} ({b.days_to_expiry} days), "
                f"Stock: {b.available} units"
                for b in batches[:10]
            ])
            
            message = f"""
⚠️ Expiry Warning for {warehouse.name}

{len(batches)} batch(es) expiring within {days_threshold} days:

{batch_list}

Please take action to avoid waste.
            """.strip()
            
            recipients = [m.customer for m in managers if m.customer]
            
            if recipients:
                message_service.send_message(
                    recipients=recipients,
                    subject=f"⚠️ Expiry Warning - {warehouse.name}",
                    message=message,
                    message_type='notification',
                    send_email=True,
                )
                notifications_sent += 1
        
        return notifications_sent

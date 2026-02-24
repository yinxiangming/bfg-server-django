# -*- coding: utf-8 -*-
"""
Customer-related condition fields for BFG Condition Engine.
"""

from typing import Dict, Any
from django.utils import timezone
from bfg.core.condition_engine import FieldProvider


class CustomerFieldProvider(FieldProvider):
    """Provides customer-related condition fields."""
    
    def get_available_fields(self) -> Dict[str, str]:
        return {
            'is_new': 'Whether customer is new (registered < 30 days)',
            'first_order': 'Whether this is customer\'s first order',
            'tier': 'Customer tier (standard/silver/gold/vip)',
            'total_orders': 'Total number of orders',
            'total_spent': 'Total amount spent',
            'registration_days': 'Days since registration',
        }
    
    def get_field_value(self, field_name: str, context: Dict[str, Any]) -> Any:
        """Get customer field value from context."""
        customer = context.get('customer_obj')
        
        if not customer:
            return None
        
        if field_name == 'is_new':
            return self._is_new_customer(customer)
        elif field_name == 'first_order':
            return self._is_first_order(customer, context.get('workspace'))
        elif field_name == 'tier':
            return getattr(customer, 'tier', 'standard')
        elif field_name == 'total_orders':
            return self._get_order_count(customer, context.get('workspace'))
        elif field_name == 'total_spent':
            return self._get_total_spent(customer, context.get('workspace'))
        elif field_name == 'registration_days':
            if hasattr(customer, 'created_at') and customer.created_at:
                return (timezone.now() - customer.created_at).days
            return None
        
        return None
    
    def _is_new_customer(self, customer) -> bool:
        """Check if customer is new (registered < 30 days)."""
        if not hasattr(customer, 'created_at') or not customer.created_at:
            return False
        days = (timezone.now() - customer.created_at).days
        return days <= 30
    
    def _is_first_order(self, customer, workspace) -> bool:
        """Check if this is customer's first order."""
        if not customer or not workspace:
            return False
        
        from bfg.shop.models import Order
        completed_count = Order.objects.filter(
            customer=customer,
            workspace=workspace,
            status__in=['delivered', 'completed']
        ).count()
        
        return completed_count == 0
    
    def _get_order_count(self, customer, workspace) -> int:
        """Get total number of customer orders."""
        if not customer or not workspace:
            return 0
        
        from bfg.shop.models import Order
        return Order.objects.filter(
            customer=customer,
            workspace=workspace
        ).count()
    
    def _get_total_spent(self, customer, workspace):
        """Get total amount spent by customer."""
        if not customer or not workspace:
            return 0
        
        from bfg.shop.models import Order
        from django.db.models import Sum
        from decimal import Decimal
        
        result = Order.objects.filter(
            customer=customer,
            workspace=workspace,
            status__in=['delivered', 'completed']
        ).aggregate(total=Sum('total_amount'))
        
        return result.get('total') or Decimal('0')

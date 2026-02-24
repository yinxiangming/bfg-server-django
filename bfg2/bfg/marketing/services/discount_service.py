"""
BFG Marketing Module - Discount Calculation Service

Handles discount calculation for orders including:
- Coupon validation and application
- Gift card application
- Discount rule evaluation
- Product/category-specific discounts
"""

from typing import List, Dict, Optional, Tuple
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q

from bfg.core.services import BaseService
from bfg.marketing.models import DiscountRule, Coupon
from bfg.marketing.models import GiftCard
from bfg.shop.models import Order, OrderItem, Product, ProductCategory
from bfg.common.models import Customer


class DiscountCalculationService(BaseService):
    """
    Discount calculation service
    
    Calculates discounts for orders based on coupons, gift cards, and discount rules
    """
    
    def calculate_order_discount(
        self,
        order_items: List[OrderItem],
        subtotal: Decimal,
        coupon_code: Optional[str] = None,
        gift_card_code: Optional[str] = None,
        customer: Optional[Customer] = None
    ) -> Dict[str, Decimal]:
        """
        Calculate total discount for an order
        
        Args:
            order_items: List of order items
            subtotal: Order subtotal
            coupon_code: Optional coupon code to apply
            gift_card_code: Optional gift card code to apply
            customer: Customer instance (for usage limits)
            
        Returns:
            Dict with:
                - discount: Total discount amount
                - shipping_discount: Shipping discount (if free shipping)
                - coupon_discount: Discount from coupon
                - gift_card_amount: Amount from gift card
        """
        result = {
            'discount': Decimal('0.00'),
            'shipping_discount': Decimal('0.00'),
            'coupon_discount': Decimal('0.00'),
            'gift_card_amount': Decimal('0.00')
        }
        
        # Calculate coupon discount (if coupon_code provided)
        if coupon_code:
            coupon_discount = self._calculate_coupon_discount(
                coupon_code=coupon_code,
                order_items=order_items,
                subtotal=subtotal,
                customer=customer
            )
            result['coupon_discount'] = coupon_discount['discount']
            result['shipping_discount'] = coupon_discount.get('shipping_discount', Decimal('0.00'))
        else:
            # Auto-apply matching discount rules (if no coupon_code provided)
            auto_discount = self._calculate_auto_discount(
                order_items=order_items,
                subtotal=subtotal,
                customer=customer
            )
            result['coupon_discount'] = auto_discount['discount']
            result['shipping_discount'] = auto_discount.get('shipping_discount', Decimal('0.00'))
        
        # Calculate gift card amount
        if gift_card_code:
            gift_card_amount = self._calculate_gift_card_amount(
                gift_card_code=gift_card_code,
                subtotal=subtotal,
                existing_discount=result['coupon_discount']
            )
            result['gift_card_amount'] = gift_card_amount
        
        # Total discount = coupon discount + gift card amount
        # Note: Gift card is applied after discount, so it reduces the total
        result['discount'] = result['coupon_discount']
        
        return result
    
    def _calculate_coupon_discount(
        self,
        coupon_code: str,
        order_items: List[OrderItem],
        subtotal: Decimal,
        customer: Optional[Customer] = None
    ) -> Dict[str, Decimal]:
        """
        Calculate discount from coupon
        
        Returns:
            Dict with 'discount' and optionally 'shipping_discount'
        """
        try:
            coupon = Coupon.objects.get(
                workspace=self.workspace,
                code=coupon_code.upper(),
                is_active=True
            )
        except Coupon.DoesNotExist:
            return {'discount': Decimal('0.00')}
        
        # Validate coupon
        validation_error = self._validate_coupon(coupon, subtotal, customer)
        if validation_error:
            # Return 0 discount if validation fails
            return {'discount': Decimal('0.00')}
        
        discount_rule = coupon.discount_rule
        
        # Check minimum purchase requirement
        if discount_rule.minimum_purchase and subtotal < discount_rule.minimum_purchase:
            return {'discount': Decimal('0.00')}
        
        # Calculate discount based on discount type
        discount = Decimal('0.00')
        shipping_discount = Decimal('0.00')
        
        if discount_rule.discount_type == 'free_shipping':
            # Free shipping discount will be handled separately
            shipping_discount = Decimal('999999.99')  # Large value to indicate free shipping
            discount = Decimal('0.00')
        elif discount_rule.discount_type == 'percentage':
            # Percentage discount
            if discount_rule.apply_to == 'order':
                # Apply to entire order
                discount = (subtotal * discount_rule.discount_value) / Decimal('100')
            elif discount_rule.apply_to == 'products':
                # Apply to specific products
                discount = self._calculate_product_discount(
                    discount_rule, order_items, 'percentage'
                )
            elif discount_rule.apply_to == 'categories':
                # Apply to specific categories
                discount = self._calculate_category_discount(
                    discount_rule, order_items, 'percentage'
                )
        elif discount_rule.discount_type == 'fixed_amount':
            # Fixed amount discount
            if discount_rule.apply_to == 'order':
                discount = discount_rule.discount_value
            elif discount_rule.apply_to == 'products':
                discount = self._calculate_product_discount(
                    discount_rule, order_items, 'fixed_amount'
                )
            elif discount_rule.apply_to == 'categories':
                discount = self._calculate_category_discount(
                    discount_rule, order_items, 'fixed_amount'
                )
        
        # Apply maximum discount cap
        if discount_rule.maximum_discount:
            discount = min(discount, discount_rule.maximum_discount)
        
        # Ensure discount doesn't exceed subtotal
        discount = min(discount, subtotal)
        
        return {
            'discount': discount,
            'shipping_discount': shipping_discount
        }
    
    def _calculate_product_discount(
        self,
        discount_rule: DiscountRule,
        order_items: List[OrderItem],
        discount_type: str
    ) -> Decimal:
        """Calculate discount for specific products"""
        applicable_product_ids = set(
            discount_rule.products.values_list('id', flat=True)
        )
        
        applicable_subtotal = Decimal('0.00')
        for item in order_items:
            # Check both product and variant
            if item.product.id in applicable_product_ids:
                applicable_subtotal += item.subtotal
            elif item.variant and item.variant.product.id in applicable_product_ids:
                applicable_subtotal += item.subtotal
        
        if applicable_subtotal == 0:
            return Decimal('0.00')
        
        if discount_type == 'percentage':
            discount = (applicable_subtotal * discount_rule.discount_value) / Decimal('100')
            # Apply maximum discount cap if set
            if discount_rule.maximum_discount:
                discount = min(discount, discount_rule.maximum_discount)
            return discount
        else:  # fixed_amount
            return discount_rule.discount_value
    
    def _calculate_category_discount(
        self,
        discount_rule: DiscountRule,
        order_items: List[OrderItem],
        discount_type: str
    ) -> Decimal:
        """Calculate discount for specific categories"""
        applicable_category_ids = set(
            discount_rule.categories.values_list('id', flat=True)
        )
        
        applicable_subtotal = Decimal('0.00')
        for item in order_items:
            # Check if product belongs to any applicable category
            product_categories = item.product.categories.values_list('id', flat=True)
            if any(cat_id in applicable_category_ids for cat_id in product_categories):
                applicable_subtotal += item.subtotal
        
        if applicable_subtotal == 0:
            return Decimal('0.00')
        
        if discount_type == 'percentage':
            discount = (applicable_subtotal * discount_rule.discount_value) / Decimal('100')
            # Apply maximum discount cap if set
            if discount_rule.maximum_discount:
                discount = min(discount, discount_rule.maximum_discount)
            return discount
        else:  # fixed_amount
            return discount_rule.discount_value
    
    def _validate_coupon(
        self,
        coupon: Coupon,
        subtotal: Decimal,
        customer: Optional[Customer] = None
    ) -> Optional[str]:
        """
        Validate coupon can be used
        
        Returns:
            Error message if invalid, None if valid
        """
        now = timezone.now()
        
        # Check validity dates
        if coupon.valid_from > now:
            return "Coupon is not yet valid"
        
        if coupon.valid_until and coupon.valid_until < now:
            return "Coupon has expired"
        
        # Check usage limits
        if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
            return "Coupon usage limit reached"
        
        # Check per-customer usage limit
        if customer and coupon.usage_limit_per_customer:
            # Count how many times this customer has used this coupon
            from bfg.shop.models import Order
            customer_usage_count = Order.objects.filter(
                workspace=self.workspace,
                customer=customer
            ).exclude(discount=Decimal('0.00')).count()  # Simplified check
            
            # Note: This is a simplified check. In production, you'd track coupon usage per order
            # For now, we'll allow it if the coupon hasn't reached its limit
            
        # Check minimum purchase requirement
        if coupon.discount_rule.minimum_purchase:
            if subtotal < coupon.discount_rule.minimum_purchase:
                return f"Minimum purchase of {coupon.discount_rule.minimum_purchase} required"
        
        return None
    
    def _calculate_gift_card_amount(
        self,
        gift_card_code: str,
        subtotal: Decimal,
        existing_discount: Decimal = Decimal('0.00')
    ) -> Decimal:
        """
        Calculate amount to apply from gift card
        
        Args:
            gift_card_code: Gift card code
            subtotal: Order subtotal
            existing_discount: Existing discount amount
            
        Returns:
            Amount to apply from gift card (cannot exceed remaining balance or order total)
        """
        try:
            gift_card = GiftCard.objects.get(
                workspace=self.workspace,
                code=gift_card_code.upper(),
                is_active=True
            )
        except GiftCard.DoesNotExist:
            return Decimal('0.00')
        
        # Check if gift card is expired
        if gift_card.expires_at and gift_card.expires_at < timezone.now():
            return Decimal('0.00')
        
        # Calculate remaining order total after discount
        remaining_total = subtotal - existing_discount
        
        # Gift card can only cover remaining amount, up to its balance
        applicable_amount = min(gift_card.balance, remaining_total)
        
        # Ensure amount is positive
        return max(applicable_amount, Decimal('0.00'))
    
    def apply_coupon_to_order(
        self,
        order: Order,
        coupon_code: str,
        customer: Optional[Customer] = None
    ) -> Tuple[Decimal, Optional[str]]:
        """
        Apply coupon to an existing order and update discount
        
        Returns:
            Tuple of (discount_amount, error_message)
        """
        order_items = list(order.items.select_related('product', 'variant').all())
        subtotal = order.subtotal
        
        discount_result = self._calculate_coupon_discount(
            coupon_code=coupon_code,
            order_items=order_items,
            subtotal=subtotal,
            customer=customer
        )
        
        discount = discount_result['discount']
        shipping_discount = discount_result.get('shipping_discount', Decimal('0.00'))
        
        # Update order discount
        order.discount = discount
        if shipping_discount > Decimal('0.00'):
            # Free shipping
            order.shipping_cost = Decimal('0.00')
        
        # Recalculate total
        order.total = order.subtotal + order.shipping_cost + order.tax - order.discount
        order.save()
        
        # Increment coupon usage
        try:
            coupon = Coupon.objects.get(
                workspace=self.workspace,
                code=coupon_code.upper()
            )
            coupon.times_used += 1
            coupon.save()
        except Coupon.DoesNotExist:
            pass
        
        return discount, None
    
    def apply_gift_card_to_order(
        self,
        order: Order,
        gift_card_code: str
    ) -> Tuple[Decimal, Optional[str]]:
        """
        Apply gift card to an existing order
        
        Returns:
            Tuple of (amount_applied, error_message)
        """
        subtotal = order.subtotal
        existing_discount = order.discount
        
        amount = self._calculate_gift_card_amount(
            gift_card_code=gift_card_code,
            subtotal=subtotal,
            existing_discount=existing_discount
        )
        
        if amount <= 0:
            return Decimal('0.00'), "Gift card cannot be applied"
        
        # Update order total (gift card reduces the amount to pay)
        # Note: Gift card is not stored as discount, but reduces the total
        # For simplicity, we'll treat it as additional discount
        order.discount += amount
        order.total = order.subtotal + order.shipping_cost + order.tax - order.discount
        order.save()
        
        # Deduct from gift card balance
        try:
            gift_card = GiftCard.objects.get(
                workspace=self.workspace,
                code=gift_card_code.upper()
            )
            gift_card.balance -= amount
            gift_card.save()
        except GiftCard.DoesNotExist:
            pass
        
        return amount, None
    
    def _calculate_auto_discount(
        self,
        order_items: List[OrderItem],
        subtotal: Decimal,
        customer: Optional[Customer] = None
    ) -> Dict[str, Decimal]:
        """
        Automatically find and apply matching discount rules
        
        This applies discount rules that match the order items without requiring a coupon code.
        Priority: order-level discounts > category discounts > product discounts
        
        Returns:
            Dict with 'discount' and optionally 'shipping_discount'
        """
        # Find active discount rules that match the order
        matching_rules = DiscountRule.objects.filter(
            workspace=self.workspace,
            is_active=True
        ).order_by('-created_at')  # Apply most recently created rule first
        
        best_discount = Decimal('0.00')
        shipping_discount = Decimal('0.00')
        best_rule = None
        
        # Try to find the best matching discount rule
        for rule in matching_rules:
            # Check minimum purchase requirement
            if rule.minimum_purchase and subtotal < rule.minimum_purchase:
                continue
            
            # Calculate discount for this rule
            rule_discount = Decimal('0.00')
            rule_shipping_discount = Decimal('0.00')
            
            if rule.discount_type == 'free_shipping':
                # Free shipping - check if it applies
                if rule.apply_to == 'order':
                    # Applies to entire order
                    rule_shipping_discount = Decimal('999999.99')
                    rule_discount = Decimal('0.00')
                elif rule.apply_to == 'products':
                    # Check if any products match
                    applicable_product_ids = set(rule.products.values_list('id', flat=True))
                    has_matching_product = any(
                        item.product.id in applicable_product_ids or
                        (item.variant and item.variant.product.id in applicable_product_ids)
                        for item in order_items
                    )
                    if has_matching_product:
                        rule_shipping_discount = Decimal('999999.99')
                elif rule.apply_to == 'categories':
                    # Check if any categories match
                    applicable_category_ids = set(rule.categories.values_list('id', flat=True))
                    has_matching_category = any(
                        any(cat_id in applicable_category_ids 
                            for cat_id in item.product.categories.values_list('id', flat=True))
                        for item in order_items
                    )
                    if has_matching_category:
                        rule_shipping_discount = Decimal('999999.99')
            elif rule.discount_type == 'percentage':
                if rule.apply_to == 'order':
                    rule_discount = (subtotal * rule.discount_value) / Decimal('100')
                elif rule.apply_to == 'products':
                    rule_discount = self._calculate_product_discount(
                        rule, order_items, 'percentage'
                    )
                elif rule.apply_to == 'categories':
                    rule_discount = self._calculate_category_discount(
                        rule, order_items, 'percentage'
                    )
            elif rule.discount_type == 'fixed_amount':
                if rule.apply_to == 'order':
                    rule_discount = rule.discount_value
                elif rule.apply_to == 'products':
                    rule_discount = self._calculate_product_discount(
                        rule, order_items, 'fixed_amount'
                    )
                elif rule.apply_to == 'categories':
                    rule_discount = self._calculate_category_discount(
                        rule, order_items, 'fixed_amount'
                    )
            
            # Apply maximum discount cap
            if rule.maximum_discount:
                rule_discount = min(rule_discount, rule.maximum_discount)
            
            # Ensure discount doesn't exceed subtotal
            rule_discount = min(rule_discount, subtotal)
            
            # Use the best (largest) discount found
            # For free shipping, prioritize it if it applies
            if rule_shipping_discount > Decimal('0.00'):
                shipping_discount = rule_shipping_discount
            if rule_discount > best_discount:
                best_discount = rule_discount
                best_rule = rule
        
        return {
            'discount': best_discount,
            'shipping_discount': shipping_discount
        }

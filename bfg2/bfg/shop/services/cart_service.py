"""
BFG Shop Module Services

Cart management service
"""

from typing import Any, Optional
from decimal import Decimal
from django.db import transaction
from bfg.core.services import BaseService
from bfg.shop.exceptions import EmptyCart, InsufficientStock
from bfg.shop.models import Cart, CartItem, Product, ProductVariant
from bfg.common.models import Customer


class CartService(BaseService):
    """
    Cart management service
    
    Handles shopping cart operations for both authenticated and anonymous users
    """
    
    def get_or_create_cart(self, customer: Customer) -> Cart:
        """
        Get or create cart for authenticated customer
        
        Args:
            customer: Customer instance
            
        Returns:
            Cart: Cart instance
        """
        self.validate_workspace_access(customer)
        
        # Use filter().first() to avoid MultipleObjectsReturned error
        # If multiple carts exist, get the most recent one
        cart = Cart.objects.filter(
            workspace=self.workspace,
            customer=customer
        ).order_by('-updated_at').first()
        
        if not cart:
            cart = Cart.objects.create(
                workspace=self.workspace,
                customer=customer
            )
        
        return cart
    
    def get_or_create_guest_cart(self, session_key: str) -> Cart:
        """
        Get or create cart for anonymous guest user
        
        Args:
            session_key: Session key for guest user
            
        Returns:
            Cart: Guest cart instance
        """
        cart, created = Cart.objects.get_or_create(
            workspace=self.workspace,
            session_key=session_key,
            customer__isnull=True
        )
        
        return cart
    
    @transaction.atomic
    def merge_guest_cart_to_customer(
        self,
        guest_session_key: str,
        customer: Customer
    ) -> Cart:
        """
        Merge guest cart to customer cart when user logs in
        
        Args:
            guest_session_key: Session key of guest cart
            customer: Customer instance
            
        Returns:
            Cart: Merged customer cart
        """
        # Get guest cart
        guest_cart = Cart.objects.filter(
            workspace=self.workspace,
            session_key=guest_session_key,
            customer__isnull=True
        ).first()
        
        if not guest_cart:
            # No guest cart, just return customer cart
            return self.get_or_create_cart(customer)
        
        # Get or create customer cart
        customer_cart = self.get_or_create_cart(customer)
        
        # Merge items from guest cart to customer cart
        for guest_item in guest_cart.items.all():
            # Check if item already exists in customer cart
            existing_item = customer_cart.items.filter(
                product=guest_item.product,
                variant=guest_item.variant
            ).first()
            
            if existing_item:
                # Update quantity
                existing_item.quantity += guest_item.quantity
                existing_item.save()
            else:
                # Move item to customer cart
                guest_item.cart = customer_cart
                guest_item.save()
        
        # Delete guest cart
        guest_cart.delete()
        
        return customer_cart
    
    @transaction.atomic
    def add_to_cart(
        self,
        cart: Cart,
        product: Product,
        quantity: int = 1,
        variant: Optional[ProductVariant] = None
    ) -> CartItem:
        """
        Add product to cart
        
        Args:
            cart: Cart instance
            product: Product to add
            quantity: Quantity to add
            variant: Product variant (optional)
            
        Returns:
            CartItem: Created or updated cart item
            
        Raises:
            InsufficientStock: If not enough stock available
        """
        self.validate_workspace_access(product)
        
        # Check stock availability
        if product.track_inventory:
            available_stock = variant.stock_quantity if variant else product.stock_quantity
            if available_stock < quantity:
                raise InsufficientStock(
                    f"Only {available_stock} units available"
                )
        
        # Get current price
        price = variant.price if variant and variant.price else product.price
        
        # Check if item already exists in cart
        cart_item = CartItem.objects.filter(
            cart=cart,
            product=product,
            variant=variant
        ).first()
        
        if cart_item:
            # Update existing item
            cart_item.quantity += quantity
            cart_item.save()
        else:
            # Create new item
            cart_item = CartItem.objects.create(
                cart=cart,
                product=product,
                variant=variant,
                quantity=quantity,
                price=price
            )
        
        return cart_item
    
    @transaction.atomic
    def update_cart_item_quantity(
        self,
        cart_item: CartItem,
        quantity: int
    ) -> CartItem:
        """
        Update cart item quantity
        
        Args:
            cart_item: CartItem instance
            quantity: New quantity
            
        Returns:
            CartItem: Updated cart item
            
        Raises:
            InsufficientStock: If not enough stock available
        """
        # Check stock availability
        product = cart_item.product
        if product.track_inventory:
            available_stock = cart_item.variant.stock_quantity if cart_item.variant else product.stock_quantity
            if available_stock < quantity:
                raise InsufficientStock(
                    f"Only {available_stock} units available"
                )
        
        cart_item.quantity = quantity
        cart_item.save()
        
        return cart_item
    
    def remove_from_cart(self, cart_item: CartItem) -> None:
        """
        Remove item from cart
        
        Args:
            cart_item: CartItem instance
        """
        cart_item.delete()
    
    @transaction.atomic
    def clear_cart(self, cart: Cart) -> None:
        """
        Clear all items from cart
        
        Args:
            cart: Cart instance
        """
        cart.items.all().delete()
    
    def calculate_cart_total(self, cart: Cart) -> Decimal:
        """
        Calculate cart total amount
        
        Args:
            cart: Cart instance
            
        Returns:
            Decimal: Total amount
        """
        total = Decimal('0.00')
        for item in cart.items.select_related('product', 'variant'):
            total += item.subtotal
        
        return total
    
    def get_cart_summary(self, cart: Cart) -> dict[str, Any]:
        """
        Get cart summary with item count and total
        
        Args:
            cart: Cart instance
            
        Returns:
            dict: Cart summary
        """
        items = cart.items.select_related('product', 'variant').all()
        
        return {
            'cart_id': cart.id,
            'item_count': items.count(),
            'total_quantity': sum(item.quantity for item in items),
            'subtotal': self.calculate_cart_total(cart),
            'items': items,
            'is_guest': cart.customer is None
        }

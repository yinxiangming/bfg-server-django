"""
BFG Shop Module Services

Order management service
"""

from typing import Any, Optional, Dict
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from bfg.core.services import BaseService
from bfg.shop.exceptions import EmptyCart, InvalidOrderStatus
from bfg.shop.models import (
    Order, OrderItem, Cart, Store
)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bfg.finance.models import Invoice, Payment
from bfg.common.models import Customer, Address
from bfg.common.services import AuditService
from bfg.delivery.models import FreightService


class OrderService(BaseService):
    """
    Order management service
    
    Handles order creation, status updates, and order lifecycle
    """
    
    def calculate_order_totals(
        self,
        cart: Cart,
        shipping_method: Optional[str] = None,
        freight_service_id: Optional[int] = None,
        coupon_code: Optional[str] = None,
        gift_card_code: Optional[str] = None,
        user: Optional[Any] = None,
        shipping_address: Optional[Address] = None
    ) -> Dict[str, Decimal]:
        """
        Calculate order totals (unified calculation for preview and order creation)
        
        Args:
            cart: Cart instance
            shipping_method: Shipping method code (matches FreightService.code or legacy 'standard'/'express')
            freight_service_id: FreightService ID for dynamic pricing (preferred over shipping_method)
            coupon_code: Optional coupon code
            gift_card_code: Optional gift card code
            user: User instance (for discount calculation)
            shipping_address: Optional shipping address for location-based tax calculation
            
        Returns:
            Dict with:
                - subtotal: Order subtotal
                - discount: Total discount amount
                - shipping_cost: Shipping cost
                - tax: Tax amount (calculated from TaxRate model)
                - total: Final total
                - shipping_discount: Free shipping indicator
        """        
        cart_items = cart.items.select_related('product', 'variant').all()
        
        if not cart_items:
            return {
                'subtotal': Decimal('0.00'),
                'discount': Decimal('0.00'),
                'shipping_cost': Decimal('0.00'),
                'tax': Decimal('0.00'),
                'total': Decimal('0.00'),
                'shipping_discount': Decimal('0.00')
            }
        
        # Calculate subtotal
        subtotal = sum(item.subtotal for item in cart_items)
        
        # Calculate discounts using discount service
        from bfg.marketing.services.discount_service import DiscountCalculationService
        discount_service = DiscountCalculationService(
            workspace=self.workspace,
            user=user
        )
        
        # Convert cart items to order items format for discount calculation
        temp_order_items = []
        for cart_item in cart_items:
            temp_item = OrderItem(
                product=cart_item.product,
                variant=cart_item.variant,
                quantity=cart_item.quantity,
                price=cart_item.price,
                subtotal=cart_item.subtotal
            )
            temp_order_items.append(temp_item)
        
        discount_result = discount_service.calculate_order_discount(
            order_items=temp_order_items,
            subtotal=subtotal,
            coupon_code=coupon_code,
            gift_card_code=gift_card_code,
            customer=cart.customer if cart.customer else None
        )
        
        discount = discount_result.get('discount', Decimal('0.00'))
        shipping_discount = discount_result.get('shipping_discount', Decimal('0.00'))
        
        # Calculate cart weight for shipping calculation
        weight = self._calculate_cart_weight(cart)
        
        # Calculate shipping cost using FreightService or legacy method
        shipping_cost = self._calculate_shipping_cost(
            shipping_method=shipping_method,
            freight_service_id=freight_service_id,
            weight=weight
        )
        
        # Apply free shipping discount if applicable
        if shipping_discount > Decimal('0.00'):
            shipping_cost = Decimal('0.00')
        
        # Calculate tax based on address or default rate
        tax = self._calculate_tax(subtotal, shipping_address)
        
        # Apply gift card amount (reduces total)
        gift_card_amount = discount_result.get('gift_card_amount', Decimal('0.00'))
        if gift_card_amount > 0:
            discount += gift_card_amount
        
        # Calculate total
        total = subtotal + shipping_cost + tax - discount
        
        return {
            'subtotal': subtotal,
            'discount': discount,
            'shipping_cost': shipping_cost,
            'tax': tax,
            'total': total,
            'shipping_discount': shipping_discount
        }
    
    def _calculate_cart_weight(self, cart: Cart) -> Decimal:
        """
        Calculate total weight from cart items.
        
        Args:
            cart: Cart instance
            
        Returns:
            Decimal: Total weight in kg
        """
        total_weight = Decimal('0')
        for item in cart.items.select_related('product', 'variant').all():
            # Use variant weight if available, otherwise product weight
            weight = Decimal('0')
            if item.variant and item.variant.weight:
                weight = item.variant.weight
            elif item.product.weight:
                weight = item.product.weight
            total_weight += weight * item.quantity
        return total_weight
    
    def _calculate_shipping_cost(
        self, 
        shipping_method: Optional[str] = None,
        freight_service_id: Optional[int] = None,
        weight: Decimal = Decimal('0')
    ) -> Decimal:
        """
        Calculate shipping cost using FreightService or fallback to legacy method.
        
        Args:
            shipping_method: Legacy shipping method ('standard' or 'express')
            freight_service_id: FreightService ID for dynamic pricing
            weight: Total weight in kg for calculation
            
        Returns:
            Decimal: Shipping cost
        """
        # Priority 1: Use FreightService if provided
        if freight_service_id:
            try:
                freight_service = FreightService.objects.get(
                    id=freight_service_id,
                    workspace=self.workspace,
                    is_active=True
                )
                return self._calculate_freight_service_cost(freight_service, weight)
            except FreightService.DoesNotExist:
                pass  # Fall back to legacy method
        
        # Priority 2: Use shipping_method to find a matching FreightService by code
        if shipping_method:
            freight_service = FreightService.objects.filter(
                workspace=self.workspace,
                code=shipping_method,
                is_active=True
            ).first()
            if freight_service:
                return self._calculate_freight_service_cost(freight_service, weight)
        
        # Priority 3: Legacy fallback for backward compatibility
        if shipping_method == 'express':
            return Decimal('20.00')
        elif shipping_method == 'standard':
            return Decimal('10.00')
        else:
            return Decimal('10.00')
    
    def _calculate_freight_service_cost(
        self, 
        freight_service: FreightService, 
        weight: Decimal
    ) -> Decimal:
        """
        Calculate shipping cost using FreightService config (bfg.delivery freight_calculator).

        Args:
            freight_service: FreightService instance
            weight: Total weight in kg
            
        Returns:
            Decimal: Calculated shipping cost
        """
        config = freight_service.config or {}
        
        # If no config, use simple base_price + price_per_kg formula
        if not config:
            base = freight_service.base_price or Decimal('0')
            per_kg = freight_service.price_per_kg or Decimal('0')
            return base + (weight * per_kg)
        
        from bfg.delivery.services.freight_calculator import calculate_shipping_cost
        from bfg.shop.services.freight_price_resolver import get_freight_price_value
        context = None
        if config.get('mode') == 'conditional':
            context = {'freight': {'weight': weight, 'order_amount': None}, 'weight': weight}
        get_price = get_freight_price_value(self.workspace)
        return calculate_shipping_cost(weight, config, context=context, get_price_value=get_price)
    
    def _calculate_tax(self, subtotal: Decimal, address: Optional[Address] = None) -> Decimal:
        """
        Calculate tax amount based on TaxRate model
        
        Args:
            subtotal: Order subtotal
            address: Optional shipping/billing address for location-based tax calculation
            
        Returns:
            Decimal: Tax amount
        """
        from decimal import Decimal
        from bfg.finance.models import TaxRate
        
        # Try to find applicable tax rate
        tax_rate = None
        
        if address and address.country:
            # Try state-specific rate first
            if address.state:
                tax_rate = TaxRate.objects.filter(
                    workspace=self.workspace,
                    country=address.country,
                    state=address.state,
                    is_active=True
                ).first()
            
            # Fall back to country-level rate
            if not tax_rate:
                tax_rate = TaxRate.objects.filter(
                    workspace=self.workspace,
                    country=address.country,
                    state='',
                    is_active=True
                ).first()
        
        # If no address or no country-specific rate found, use default rate
        # (first active rate with empty country, or first active rate)
        if not tax_rate:
            tax_rate = TaxRate.objects.filter(
                workspace=self.workspace,
                country='',
                state='',
                is_active=True
            ).first()
        
        if not tax_rate:
            # Fallback: try any active rate for this workspace
            tax_rate = TaxRate.objects.filter(
                workspace=self.workspace,
                is_active=True
            ).first()
        
        if tax_rate:
            # Rate is stored as percentage (e.g., 10 for 10%), convert to decimal
            tax_amount = (subtotal * tax_rate.rate) / Decimal('100')
            return tax_amount.quantize(Decimal('0.01'))
        else:
            # No tax rate configured, return 0
            return Decimal('0.00')
    
    @transaction.atomic
    def create_order_from_cart(
        self,
        cart: Cart,
        store: Store,
        shipping_address: Address,
        billing_address: Optional[Address] = None,
        **kwargs: Any
    ) -> Order:
        """
        Create order from shopping cart
        
        Args:
            cart: Cart instance
            store: Store instance
            shipping_address: Shipping address
            billing_address: Billing address (defaults to shipping)
            **kwargs: Additional order fields
            
        Returns:
            Order: Created order instance
            
        Raises:
            EmptyCart: If cart is empty
        """
        self.validate_workspace_access(cart)
        self.validate_workspace_access(store)
        
        # Check cart has items
        cart_items = cart.items.select_related('product', 'variant').all()
        if not cart_items:
            raise EmptyCart("Cannot create order from empty cart")
        
        # Use shipping address as billing if not provided
        if not billing_address:
            billing_address = shipping_address
        
        # Use unified price calculation
        # Priority: freight_service_id > shipping_method > provided shipping_cost
        shipping_method = kwargs.get('shipping_method')
        freight_service_id = kwargs.get('freight_service_id')
        coupon_code = kwargs.get('coupon_code')
        gift_card_code = kwargs.get('gift_card_code')
        
        if freight_service_id is not None or shipping_method is not None:
            # Use unified calculation function with FreightService support
            totals = self.calculate_order_totals(
                cart=cart,
                shipping_method=shipping_method,
                freight_service_id=freight_service_id,
                coupon_code=coupon_code,
                gift_card_code=gift_card_code,
                user=kwargs.get('user'),
                shipping_address=shipping_address
            )
            subtotal = totals['subtotal']
            discount = totals['discount']
            shipping_cost = totals['shipping_cost']
            tax = totals['tax']
            total = totals['total']
        else:
            # Backward compatibility: use provided shipping_cost and tax
            # But still calculate discount using unified method
            totals = self.calculate_order_totals(
                cart=cart,
                shipping_method=None,
                freight_service_id=None,
                coupon_code=coupon_code,
                gift_card_code=gift_card_code,
                user=kwargs.get('user'),
                shipping_address=shipping_address
            )
            subtotal = totals['subtotal']
            discount = totals['discount']
            
            # Use provided shipping_cost and tax if available, otherwise use calculated
            shipping_cost = kwargs.get('shipping_cost')
            if shipping_cost is not None:
                shipping_cost = Decimal(str(shipping_cost))
                # Apply free shipping discount if applicable
                if totals['shipping_discount'] > Decimal('0.00'):
                    shipping_cost = Decimal('0.00')
            else:
                shipping_cost = totals['shipping_cost']
            
            tax = kwargs.get('tax')
            if tax is not None:
                tax = Decimal(str(tax))
            else:
                tax = totals['tax']
            
            total = subtotal + shipping_cost + tax - discount
        
        # Get freight_service object if freight_service_id is provided
        freight_service = None
        if freight_service_id:
            from bfg.delivery.models import FreightService
            try:
                freight_service = FreightService.objects.get(
                    id=freight_service_id,
                    workspace=self.workspace,
                    is_active=True
                )
            except FreightService.DoesNotExist:
                pass  # Keep as None if not found
        
        # Generate order number
        order_number = self._generate_order_number()
        
        # Create order
        order = Order.objects.create(
            workspace=self.workspace,
            customer=cart.customer,
            store=store,
            order_number=order_number,
            status='pending',
            payment_status='pending',
            subtotal=subtotal,
            shipping_cost=shipping_cost,
            tax=tax,
            discount=discount,
            total=total,
            shipping_address=shipping_address,
            billing_address=billing_address,
            customer_note=kwargs.get('customer_note', ''),
            admin_note=kwargs.get('admin_note', ''),
            freight_service=freight_service,
        )
        
        # Get default warehouse for inventory operations
        from bfg.delivery.models import Warehouse
        default_warehouse = Warehouse.objects.filter(
            workspace=self.workspace,
            is_active=True
        ).order_by('-is_default', 'name').first()
        
        # Create order items from cart items and handle inventory
        from bfg.shop.services.inventory_service import InventoryService
        inventory_service = InventoryService(
            workspace=self.workspace,
            user=self.user
        )
        
        for cart_item in cart_items:
            OrderItem.objects.create(
                order=order,
                product=cart_item.product,
                variant=cart_item.variant,
                product_name=cart_item.product.name,
                variant_name=cart_item.variant.name if cart_item.variant else '',
                sku=cart_item.variant.sku if cart_item.variant else cart_item.product.sku,
                quantity=cart_item.quantity,
                price=cart_item.price,
                subtotal=cart_item.subtotal,
            )
            
            # Reserve stock if inventory tracking is enabled
            # Note: For products with variants, we reserve stock (will be fulfilled on payment)
            # For products without variants, we check stock availability but don't reserve
            # (will be deducted directly on payment completion)
            if cart_item.product.track_inventory and default_warehouse:
                try:
                    if cart_item.variant:
                        # Product with variant: reserve stock using VariantInventory
                        inventory_service.reserve_stock(
                            variant=cart_item.variant,
                            warehouse=default_warehouse,
                            quantity=cart_item.quantity
                        )
                    # For products without variants, stock will be deducted on payment completion
                except Exception as e:
                    # Log error but don't fail order creation
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"Failed to reserve stock for product {cart_item.product.id} "
                        f"(variant: {cart_item.variant.id if cart_item.variant else 'None'}) "
                        f"in order {order.order_number}: {e}"
                    )
        
        # Clear cart after order creation
        cart.items.all().delete()
        
        # Auto-create Invoice
        invoice = self._create_invoice_for_order(order)
        
        # Auto-create pending Payment record
        self._create_payment_for_order(order, invoice)
        
        # Log order creation
        audit = AuditService(workspace=self.workspace, user=self.user)
        audit.log_create(
            order,
            description=f"Order {order.order_number} was placed - Total: {order.total}",
        )
        
        # Emit order created event
        self.emit_event('order.created', {'order': order})
        
        return order
    
    @transaction.atomic
    def create_order(
        self,
        customer: Customer,
        store: Store,
        shipping_address: Address,
        billing_address: Optional[Address] = None,
        **kwargs: Any
    ) -> Order:
        """
        Create order directly (not from cart)
        
        Args:
            customer: Customer instance
            store: Store instance
            shipping_address: Shipping address
            billing_address: Billing address (defaults to shipping)
            **kwargs: Additional order fields
                - subtotal: Order subtotal (required)
                - total: Order total (required)
                - shipping_cost: Shipping cost (default: 0)
                - tax: Tax amount (default: 0)
                - discount: Discount amount (default: 0)
                - status: Order status (default: 'pending')
                - payment_status: Payment status (default: 'pending')
                - customer_note: Customer note
                - admin_note: Admin note
                - order_items: List of order items data (optional)
            
        Returns:
            Order: Created order instance
        """
        self.validate_workspace_access(customer)
        self.validate_workspace_access(store)
        
        # Use shipping address as billing if not provided
        if not billing_address:
            billing_address = shipping_address
        
        # Get order data
        subtotal = kwargs.get('subtotal', Decimal('0.00'))
        shipping_cost = kwargs.get('shipping_cost', Decimal('0.00'))
        tax = kwargs.get('tax', Decimal('0.00'))
        discount = kwargs.get('discount', Decimal('0.00'))
        total = kwargs.get('total', subtotal + shipping_cost + tax - discount)
        status = kwargs.get('status', 'pending')
        payment_status = kwargs.get('payment_status', 'pending')
        
        # Generate order number
        order_number = self._generate_order_number()
        
        # Create order
        order = Order.objects.create(
            workspace=self.workspace,
            customer=customer,
            store=store,
            order_number=order_number,
            status=status,
            payment_status=payment_status,
            subtotal=subtotal,
            shipping_cost=shipping_cost,
            tax=tax,
            discount=discount,
            total=total,
            shipping_address=shipping_address,
            billing_address=billing_address,
            customer_note=kwargs.get('customer_note', ''),
            admin_note=kwargs.get('admin_note', ''),
        )
        
        # Create order items if provided
        order_items = kwargs.get('order_items', [])
        for item_data in order_items:
            from bfg.shop.models import Product, ProductVariant
            product = Product.objects.get(id=item_data['product_id'], workspace=self.workspace)
            variant = None
            if item_data.get('variant_id'):
                variant = ProductVariant.objects.get(id=item_data['variant_id'])
            
            OrderItem.objects.create(
                order=order,
                product=product,
                variant=variant,
                product_name=product.name,
                variant_name=variant.name if variant else '',
                sku=variant.sku if variant else product.sku,
                quantity=item_data.get('quantity', 1),
                price=item_data.get('price', product.price),
                subtotal=item_data.get('subtotal', Decimal('0.00')),
            )
        
        # Emit order created event
        self.emit_event('order.created', {'order': order})
        
        return order
    
    def _generate_order_number(self) -> str:
        """
        Generate unique order number
        
        Returns:
            str: Order number
        """
        import random
        import string
        
        # Format: ORD-YYYYMMDD-XXXXX
        date_str = timezone.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.digits, k=5))
        
        order_number = f"ORD-{date_str}-{random_str}"
        
        # Ensure uniqueness
        while Order.objects.filter(order_number=order_number).exists():
            random_str = ''.join(random.choices(string.digits, k=5))
            order_number = f"ORD-{date_str}-{random_str}"
        
        return order_number
    
    def _create_invoice_for_order(self, order: Order) -> Optional['Invoice']:
        """
        Auto-create invoice for order
        
        Args:
            order: Order instance
            
        Returns:
            Invoice: Created invoice or None if failed
        """
        try:
            from bfg.finance.models import Currency
            from bfg.finance.services.invoice_service import InvoiceService
            
            # Get default currency (USD) or first active currency
            currency = Currency.objects.filter(code='USD', is_active=True).first()
            if not currency:
                currency = Currency.objects.filter(is_active=True).first()
            
            if not currency:
                # Create default USD currency if not exists
                currency, _ = Currency.objects.get_or_create(
                    code='USD',
                    defaults={'name': 'US Dollar', 'symbol': '$', 'is_active': True}
                )
            
            invoice_service = InvoiceService(
                workspace=self.workspace,
                user=self.user
            )
            
            invoice = invoice_service.create_invoice_from_order(order, currency)
            return invoice
        except Exception as e:
            # Log error but don't fail order creation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to create invoice for order {order.order_number}: {e}")
            return None
    
    def _create_payment_for_order(self, order: Order, invoice: Optional['Invoice'] = None) -> Optional['Payment']:
        """
        Auto-create pending payment record for order
        
        Args:
            order: Order instance
            invoice: Invoice instance (optional)
            
        Returns:
            Payment: Created payment or None if failed
        """
        try:
            from bfg.finance.models import Currency, PaymentGateway, Payment
            from bfg.finance.services.payment_service import PaymentService
            
            # Get default currency
            currency = Currency.objects.filter(code='USD', is_active=True).first()
            if not currency:
                currency = Currency.objects.filter(is_active=True).first()
            
            if not currency:
                currency, _ = Currency.objects.get_or_create(
                    code='USD',
                    defaults={'name': 'US Dollar', 'symbol': '$', 'is_active': True}
                )
            
            # Get first active payment gateway
            gateway = PaymentGateway.objects.filter(
                workspace=self.workspace,
                is_active=True
            ).first()
            
            if not gateway:
                # No gateway configured, skip payment creation
                return None
            
            payment_service = PaymentService(
                workspace=self.workspace,
                user=self.user
            )
            
            payment = payment_service.create_payment(
                customer=order.customer,
                amount=order.total,
                currency=currency,
                gateway=gateway,
                order=order,
                invoice=invoice
            )
            return payment
        except Exception as e:
            # Log error but don't fail order creation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to create payment for order {order.order_number}: {e}")
            return None
    
    @transaction.atomic
    def update_order_status(
        self,
        order: Order,
        new_status: str
    ) -> Order:
        """
        Update order status
        
        Args:
            order: Order instance
            new_status: New status value
            
        Returns:
            Order: Updated order instance
        """
        self.validate_workspace_access(order)
        
        old_status = order.status
        order.status = new_status
        
        # Update timestamps based on status
        if new_status == 'shipped' and not order.shipped_at:
            order.shipped_at = timezone.now()
            self.emit_event('order.shipped', {'order': order})
        elif new_status == 'delivered' and not order.delivered_at:
            order.delivered_at = timezone.now()
            self.emit_event('order.delivered', {'order': order})
        elif new_status == 'processing' and old_status == 'pending':
            # Emit processing event (optional notification)
            self.emit_event('order.processing', {'order': order})
        elif new_status == 'cancelled':
            # Emit cancellation event
            self.emit_event('order.cancelled', {
                'order': order,
                'old_status': old_status
            })
        elif new_status == 'refunded':
            # Emit refund event
            self.emit_event('order.refunded', {
                'order': order,
                'old_status': old_status
            })
        
        order.save()
        
        # Log status change
        audit = AuditService(workspace=self.workspace, user=self.user)
        status_display = dict(Order.STATUS_CHOICES).get(new_status, new_status)
        audit.log_update(
            order,
            changes={'status': {'old': old_status, 'new': new_status}},
            description=f"Order status changed to {status_display}",
        )
        
        return order
    
    @transaction.atomic
    def mark_as_paid(self, order: Order) -> Order:
        """
        Mark order as paid and fulfill inventory reservations
        
        Args:
            order: Order instance
            
        Returns:
            Order: Updated order instance
        """
        self.validate_workspace_access(order)
        
        old_payment_status = order.payment_status
        order.payment_status = 'paid'
        order.paid_at = timezone.now()
        order.save()
        
        # Fulfill inventory reservations (deduct stock)
        from bfg.delivery.models import Warehouse
        from bfg.shop.services.inventory_service import InventoryService
        
        default_warehouse = Warehouse.objects.filter(
            workspace=self.workspace,
            is_active=True
        ).order_by('-is_default', 'name').first()
        
        if default_warehouse:
            inventory_service = InventoryService(
                workspace=self.workspace,
                user=self.user
            )
            
            # Process each order item
            for order_item in order.items.select_related('product', 'variant').all():
                if order_item.product.track_inventory:
                    try:
                        if order_item.variant:
                            # Product with variant: fulfill reservation (deduct from quantity and reserved)
                            inventory_service.fulfill_reservation(
                                variant=order_item.variant,
                                warehouse=default_warehouse,
                                quantity=order_item.quantity
                            )
                        else:
                            # Product without variant: directly deduct from Product.stock_quantity
                            from django.db.models import F
                            from bfg.shop.models import Product
                            Product.objects.filter(id=order_item.product.id).update(
                                stock_quantity=F('stock_quantity') - order_item.quantity
                            )
                    except Exception as e:
                        # Log error but don't fail payment marking
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"Failed to fulfill inventory reservation for product {order_item.product.id} "
                            f"(variant: {order_item.variant.id if order_item.variant else 'None'}) "
                            f"in order {order.order_number}: {e}"
                        )
        
        # Log payment status change
        audit = AuditService(workspace=self.workspace, user=self.user)
        audit.log_update(
            order,
            changes={'payment_status': {'old': old_payment_status, 'new': 'paid'}},
            description=f"Order {order.order_number} marked as paid",
        )
        
        # Emit payment confirmed event
        self.emit_event('order.paid', {'order': order})
        
        return order
    
    def cancel_order(self, order: Order, reason: str = '') -> Order:
        """
        Cancel order
        
        Args:
            order: Order instance
            reason: Cancellation reason
            
        Returns:
            Order: Updated order instance
            
        Raises:
            InvalidOrderStatus: If order cannot be cancelled
        """
        self.validate_workspace_access(order)
        
        # Check if order can be cancelled
        if order.status in ['delivered', 'cancelled', 'refunded']:
            from bfg.shop.exceptions import OrderNotCancellable
            raise OrderNotCancellable(
                f"Order in '{order.status}' status cannot be cancelled"
            )
        
        old_status = order.status
        order.status = 'cancelled'
        if reason:
            order.admin_note = f"Cancelled: {reason}\n{order.admin_note}"
        order.save()
        
        # Emit cancellation event
        self.emit_event('order.cancelled', {
            'order': order,
            'old_status': old_status,
            'reason': reason
        })
        
        # Log cancellation
        audit = AuditService(workspace=self.workspace, user=self.user)
        description = f"Order {order.order_number} was cancelled"
        if reason:
            description += f" - Reason: {reason}"
        audit.log_update(
            order,
            changes={'status': {'old': old_status, 'new': 'cancelled'}},
            description=description,
        )
        
        return order
    
    def get_customer_orders(
        self,
        customer: Customer,
        status: Optional[str] = None
    ):
        """
        Get orders for customer
        
        Args:
            customer: Customer instance
            status: Filter by status (optional)
            
        Returns:
            QuerySet: Customer orders
        """
        queryset = Order.objects.filter(
            workspace=self.workspace,
            customer=customer
        ).select_related('store').prefetch_related('items')
        
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-created_at')

"""
BFG Shop Module Services

Order management service
"""

from typing import Any, Optional, Dict
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from bfg.core.services import BaseService
from rest_framework.exceptions import ValidationError as APIValidationError

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
        shipping_address: Optional[Address] = None,
        fulfillment_method: str = 'shipping',
        pickup_point: Optional[Any] = None
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
            fulfillment_method: 'shipping' or 'pickup'
            pickup_point: PickupPoint the customer collects from, when picking up
            
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
        
        if fulfillment_method == 'pickup':
            # Nothing is being carried, so weight bands and freight services have
            # nothing to say here. What the shopper pays, if anything, is what the
            # point charges for holding the order.
            shipping_cost = pickup_point.fee if pickup_point is not None else Decimal('0.00')
        else:
            # Calculate cart weight for shipping calculation
            weight = self._calculate_cart_weight(cart)

            # Calculate shipping cost using FreightService or legacy method
            shipping_cost = self._calculate_shipping_cost(
                shipping_method=shipping_method,
                freight_service_id=freight_service_id,
                weight=weight,
                order_amount=subtotal
            )
        
        # Apply free shipping discount if applicable
        if shipping_discount > Decimal('0.00'):
            shipping_cost = Decimal('0.00')
        
        # Calculate tax based on address or default rate
        tax = self._calculate_tax(subtotal, shipping_address)
        
        gift_card_amount = discount_result.get('gift_card_amount', Decimal('0.00'))
        if gift_card_amount > 0:
            discount += gift_card_amount
        
        # Calculate total
        total = max(subtotal + shipping_cost + tax - discount, Decimal('0.00'))
        
        return {
            'subtotal': subtotal,
            'discount': discount,
            'shipping_cost': shipping_cost,
            'tax': tax,
            'total': total,
            'shipping_discount': shipping_discount,
            'coupon_discount': discount_result.get('coupon_discount', Decimal('0.00')),
            'gift_card_amount': gift_card_amount,
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
        weight: Decimal = Decimal('0'),
        order_amount: Decimal = Decimal('0')
    ) -> Decimal:
        """
        Calculate shipping cost using FreightService or fallback to legacy method.
        
        Args:
            shipping_method: Legacy shipping method ('standard' or 'express')
            freight_service_id: FreightService ID for dynamic pricing
            weight: Total weight in kg for calculation
            order_amount: Merchandise subtotal, for value-threshold pricing rules
            
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
                return self._calculate_freight_service_cost(freight_service, weight, order_amount)
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
                return self._calculate_freight_service_cost(freight_service, weight, order_amount)
        
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
        weight: Decimal,
        order_amount: Decimal = Decimal('0')
    ) -> Decimal:
        """
        Calculate shipping cost using FreightService config (bfg.delivery freight_calculator).

        Args:
            freight_service: FreightService instance
            weight: Total weight in kg
            order_amount: Merchandise subtotal, for value-threshold pricing rules
            
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
            # order_amount was hardcoded to None here, and the engine treats a None
            # actual as "no match" — so every `order_amount_gte` rule silently failed and
            # the shipped `free_over_amount` template could never grant free shipping on
            # the storefront. It only ever worked in the back office, which passes a real
            # figure. Use the merchandise subtotal, matching `order.subtotal` there, so a
            # quote and a later admin recalculation agree.
            context = {
                'freight': {'weight': weight, 'order_amount': order_amount},
                'weight': weight,
            }
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
    
    def resolve_pickup_point(self, fulfillment_method: str, pickup_point: Any = None):
        """The PickupPoint an order is collected from, or None when it ships.

        Takes an instance or an id. A pickup order that names no point falls back
        to the workspace default -- that is what ``is_default`` is for, and it
        saves single-point shops from sending an id they have no choice about.
        With no default configured there is nothing sensible to guess, so it is a
        400 rather than a pickup order nobody can collect.
        """
        if fulfillment_method != 'pickup':
            return None

        from bfg.delivery.models import PickupPoint

        if pickup_point is not None and not isinstance(pickup_point, PickupPoint):
            pickup_point = PickupPoint.objects.filter(
                id=pickup_point, workspace=self.workspace, is_active=True
            ).first()
            if pickup_point is None:
                raise APIValidationError(
                    {'pickup_point': 'No such active pickup point in this workspace.'}
                )

        if pickup_point is None:
            pickup_point = PickupPoint.objects.filter(
                workspace=self.workspace, is_active=True, is_default=True
            ).first()

        if pickup_point is None:
            raise APIValidationError(
                {'pickup_point': 'Pickup point is required for pickup orders.'}
            )

        self.validate_workspace_access(pickup_point)
        return pickup_point

    @transaction.atomic
    def create_order_from_cart(
        self,
        cart: Cart,
        store: Store,
        shipping_address: Optional[Address] = None,
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
        if cart.workspace_id != store.workspace_id:
            raise APIValidationError({'store': 'Store does not belong to this cart workspace.'})

        # Serialize checkout attempts for the same cart. Once the first checkout
        # clears the rows, a concurrent request observes an empty cart instead of
        # creating a duplicate order.
        cart = Cart.all_objects.select_for_update().get(
            pk=cart.pk,
            workspace=self.workspace,
        )
        
        # Check cart has items
        cart_items = cart.items.select_related('product', 'variant').all()
        if not cart_items:
            raise EmptyCart("Cannot create order from empty cart")
        
        # Use shipping address as billing if not provided
        fulfillment_method = kwargs.get('fulfillment_method', 'shipping')
        if fulfillment_method == 'shipping' and not shipping_address:
            raise APIValidationError({'shipping_address': 'Shipping address is required for shipping orders.'})
        pickup_point = self.resolve_pickup_point(fulfillment_method, kwargs.get('pickup_point'))
        if not billing_address:
            billing_address = shipping_address

        for field_name, address in (
            ('shipping_address', shipping_address),
            ('billing_address', billing_address),
        ):
            if address is None:
                continue
            self.validate_workspace_access(address)
            if cart.customer_id is None or address.content_object != cart.customer:
                raise APIValidationError({field_name: 'Address does not belong to this customer.'})
        
        # Use unified price calculation
        # Priority: freight_service_id > shipping_method > provided shipping_cost
        shipping_method = kwargs.get('shipping_method')
        freight_service_id = kwargs.get('freight_service_id')
        coupon_code = kwargs.get('coupon_code')
        gift_card_code = kwargs.get('gift_card_code')
        
        # Prices are always server-derived. Legacy client-supplied shipping_cost,
        # tax and total values are intentionally ignored.
        totals = self.calculate_order_totals(
            cart=cart,
            shipping_method=shipping_method,
            freight_service_id=freight_service_id,
            coupon_code=coupon_code,
            gift_card_code=gift_card_code,
            user=kwargs.get('user'),
            shipping_address=shipping_address,
            fulfillment_method=fulfillment_method,
            pickup_point=pickup_point,
        )
        subtotal = totals['subtotal']
        discount = totals['discount']
        shipping_cost = totals['shipping_cost']
        tax = totals['tax']
        total = totals['total']

        coupon_row_to_record = None
        if coupon_code:
            code_upper = str(coupon_code).strip().upper()
            if code_upper:
                from bfg.marketing.models import Coupon
                from bfg.marketing.services.discount_service import DiscountCalculationService

                try:
                    coupon_row = Coupon.objects.select_for_update().get(
                        workspace=self.workspace,
                        code=code_upper,
                        is_active=True,
                    )
                except Coupon.DoesNotExist:
                    raise APIValidationError(
                        {'coupon_code': 'Invalid or inactive coupon.'}
                    )
                disc_svc = DiscountCalculationService(
                    workspace=self.workspace,
                    user=kwargs.get('user'),
                )
                cust = cart.customer if cart.customer else None
                v_err = disc_svc._validate_coupon(coupon_row, subtotal, cust)
                if v_err:
                    # Includes usage-limit exhaustion: expected business response (4xx), not a server fault
                    raise APIValidationError({'coupon_code': v_err})
                coupon_row_to_record = coupon_row

        gift_card_row_to_debit = None
        gift_card_amount = totals.get('gift_card_amount', Decimal('0.00'))
        if gift_card_code:
            from bfg.marketing.models import GiftCard

            try:
                gift_card_row_to_debit = GiftCard.objects.select_for_update().select_related('currency').get(
                    workspace=self.workspace,
                    code=str(gift_card_code).strip().upper(),
                    is_active=True,
                )
            except GiftCard.DoesNotExist:
                raise APIValidationError({'gift_card_code': 'Invalid or inactive gift card.'})
            if gift_card_row_to_debit.expires_at and gift_card_row_to_debit.expires_at < timezone.localdate():
                raise APIValidationError({'gift_card_code': 'Gift card has expired.'})
            if gift_card_row_to_debit.customer_id not in (None, cart.customer_id):
                raise APIValidationError({'gift_card_code': 'Gift card does not belong to this customer.'})
            from bfg.common.constants import get_default_currency_for_workspace
            if gift_card_row_to_debit.currency.code != get_default_currency_for_workspace(self.workspace):
                raise APIValidationError({'gift_card_code': 'Gift card currency does not match the order currency.'})

            payable_before_gift = max(
                subtotal + shipping_cost + tax - totals.get('coupon_discount', Decimal('0.00')),
                Decimal('0.00'),
            )
            gift_card_amount = min(gift_card_row_to_debit.balance, payable_before_gift)
            if gift_card_amount <= 0:
                raise APIValidationError({'gift_card_code': 'Gift card has no available balance.'})
            discount = totals.get('coupon_discount', Decimal('0.00')) + gift_card_amount
            total = max(subtotal + shipping_cost + tax - discount, Decimal('0.00'))
        
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
            fulfillment_method=fulfillment_method,
            pickup_point=pickup_point,
            pickup_code=kwargs.get('pickup_code', ''),
            subtotal=subtotal,
            shipping_cost=shipping_cost,
            tax=tax,
            discount=discount,
            total=total,
            coupon=coupon_row_to_record,
            shipping_address=shipping_address,
            billing_address=billing_address,
            customer_note=kwargs.get('customer_note', ''),
            admin_note=kwargs.get('admin_note', ''),
            freight_service=freight_service,
        )
        
        # Create all item snapshots before reserving so ownership is durable and complete.
        for cart_item in cart_items:
            OrderItem.objects.create(
                order=order, product=cart_item.product, variant=cart_item.variant,
                product_name=cart_item.product.name,
                variant_name=cart_item.variant.name if cart_item.variant else '',
                sku=cart_item.variant.sku if cart_item.variant else cart_item.product.sku,
                quantity=cart_item.quantity, price=cart_item.price, subtotal=cart_item.subtotal,
            )
        try:
            order = self.reserve_stock_for_order(order)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning('Stock reservation failed for order %s: %s', order.pk, exc)
            order.refresh_from_db(fields=['stock_error'])

        # Clear cart after order creation
        cart.items.all().delete()

        # Record coupon use after successful checkout (enforces usage_limit on next attempt)
        if coupon_row_to_record is not None:
            from bfg.marketing.models import Coupon as CouponModel

            CouponModel.objects.filter(pk=coupon_row_to_record.pk).update(
                times_used=F('times_used') + 1
            )

        if gift_card_row_to_debit is not None:
            gift_card_row_to_debit.balance -= gift_card_amount
            if gift_card_row_to_debit.balance == 0:
                gift_card_row_to_debit.is_active = False
            gift_card_row_to_debit.save(update_fields=['balance', 'is_active', 'updated_at'])
        
        # Auto-create Invoice
        invoice = self._create_invoice_for_order(order)

        if order.total == 0 and gift_card_row_to_debit is not None:
            self.mark_as_paid(order)
            if invoice is not None:
                invoice.status = 'paid'
                invoice.paid_date = timezone.now().date()
                invoice.save(update_fields=['status', 'paid_date', 'updated_at'])
        # A payment attempt is created only after the shopper chooses a gateway.
        # Pre-creating one here binds an arbitrary gateway and makes retries or a
        # saved payment method ambiguous.
        
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
        shipping_address: Optional[Address] = None,
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
        fulfillment_method = kwargs.get('fulfillment_method', 'shipping')
        if fulfillment_method == 'shipping' and not shipping_address:
            raise APIValidationError({'shipping_address': 'Shipping address is required for shipping orders.'})
        pickup_point = self.resolve_pickup_point(fulfillment_method, kwargs.get('pickup_point'))
        if not billing_address:
            billing_address = shipping_address

        for field_name, address in (
            ('shipping_address', shipping_address),
            ('billing_address', billing_address),
        ):
            if address is None:
                continue
            self.validate_workspace_access(address)
            if address.content_object != customer:
                raise APIValidationError({field_name: 'Address does not belong to this customer.'})

        prepared_items = []
        raw_items = kwargs.get('order_items', [])
        if raw_items:
            from bfg.shop.models import Product, ProductVariant

            calculated_subtotal = Decimal('0.00')
            for item_data in raw_items:
                product = Product.objects.get(id=item_data['product_id'], workspace=self.workspace)
                quantity = int(item_data.get('quantity', 1))
                if quantity <= 0 or quantity > 10000:
                    raise APIValidationError({'order_items': 'Quantity must be between 1 and 10000.'})
                variant = None
                if item_data.get('variant_id'):
                    variant = ProductVariant.objects.get(
                        id=item_data['variant_id'],
                        product=product,
                    )
                price = variant.price if variant and variant.price is not None else product.price
                line_subtotal = price * quantity
                calculated_subtotal += line_subtotal
                prepared_items.append((product, variant, quantity, price, line_subtotal))
            subtotal = calculated_subtotal
        else:
            subtotal = Decimal(str(kwargs.get('subtotal', Decimal('0.00'))))

        shipping_cost = Decimal(str(kwargs.get('shipping_cost', Decimal('0.00'))))
        tax = Decimal(str(kwargs.get('tax', Decimal('0.00'))))
        discount = Decimal(str(kwargs.get('discount', Decimal('0.00'))))
        if min(subtotal, shipping_cost, tax, discount) < 0:
            raise APIValidationError({'amounts': 'Order amounts must not be negative.'})
        gross_total = subtotal + shipping_cost + tax
        if discount > gross_total:
            raise APIValidationError({'discount': 'Discount cannot exceed the order amount.'})
        total = gross_total - discount
        status = 'pending'
        payment_status = 'pending'
        
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
            fulfillment_method=fulfillment_method,
            pickup_point=pickup_point,
            pickup_code=kwargs.get('pickup_code', ''),
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
        for product, variant, quantity, price, line_subtotal in prepared_items:
            OrderItem.objects.create(
                order=order,
                product=product,
                variant=variant,
                product_name=product.name,
                variant_name=variant.name if variant else '',
                sku=variant.sku if variant else product.sku,
                quantity=quantity,
                price=price,
                subtotal=line_subtotal,
            )
        
        # Emit order created event
        self.emit_event('order.created', {'order': order})
        
        return order
    
    def _generate_order_number(self) -> str:
        """
        Generate an order number not yet used in this workspace
        
        Returns:
            str: Order number
        """
        import random
        import string
        
        # Format: ORD-YYYYMMDD-XXXXX
        date_str = timezone.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.digits, k=5))
        
        order_number = f"ORD-{date_str}-{random_str}"
        
        # Unique within the workspace, as the model constraint is. Filter on
        # self.workspace rather than rely on the thread-bound scope of Order.objects.
        while Order.all_objects.filter(workspace=self.workspace, order_number=order_number).exists():
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
            
            from bfg.common.constants import get_default_currency_for_workspace, CURRENCY_SYMBOLS, CURRENCY_NAMES
            default_code = get_default_currency_for_workspace(self.workspace)
            currency = Currency.objects.filter(code=default_code, is_active=True).first()
            if not currency:
                currency = Currency.objects.filter(is_active=True).first()
            if not currency:
                symbol = CURRENCY_SYMBOLS.get(default_code, default_code)
                name = CURRENCY_NAMES.get(default_code, default_code)
                currency, _ = Currency.objects.get_or_create(
                    code=default_code,
                    defaults={'name': name, 'symbol': symbol, 'is_active': True}
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
            
            from bfg.common.constants import get_default_currency_for_workspace, CURRENCY_SYMBOLS, CURRENCY_NAMES
            default_code = get_default_currency_for_workspace(self.workspace)
            currency = Currency.objects.filter(code=default_code, is_active=True).first()
            if not currency:
                currency = Currency.objects.filter(is_active=True).first()
            if not currency:
                symbol = CURRENCY_SYMBOLS.get(default_code, default_code)
                name = CURRENCY_NAMES.get(default_code, default_code)
                currency, _ = Currency.objects.get_or_create(
                    code=default_code,
                    defaults={'name': name, 'symbol': symbol, 'is_active': True}
                )
            
            # Get first active payment gateway the order's fulfillment allows. Without
            # the filter a pay-at-the-counter gateway that happened to come back first
            # would be attached to an order being posted, and the money could never be
            # collected.
            from bfg.finance.gateways.loader import gateway_supports_fulfillment_method
            gateway = next(
                (
                    g for g in PaymentGateway.objects.filter(
                        workspace=self.workspace,
                        is_active=True
                    )
                    if gateway_supports_fulfillment_method(g.gateway_type, order.fulfillment_method)
                ),
                None,
            )
            
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
        
        if new_status == 'cancelled':
            order = self.release_stock_reservations(order)
        old_status = order.status
        order.status = new_status
        
        # Update timestamps based on status
        if new_status == 'shipped' and not order.shipped_at:
            order.shipped_at = timezone.now()
            self.emit_event('order.shipped', {'order': order})
        elif new_status == 'ready_for_pickup' and not order.shipped_at:
            # Same column, different sentence: the moment the order stopped
            # waiting on us. It must not raise `order.shipped` -- that event's
            # handler tells the customer a parcel is on its way, and nothing is.
            order.shipped_at = timezone.now()
            self.emit_event('order.ready_for_pickup', {'order': order})
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
    
    def _record_stock_error(self, order, exc):
        detail = str(exc)[:255] if isinstance(exc, ValueError) else 'Stock update failed; reconcile inventory.'
        Order.all_objects.filter(pk=order.pk, workspace=self.workspace).update(stock_error=detail)

    def reserve_stock_for_order(self, order: Order) -> Order:
        """Create reservations owned by each item; keep errors outside the rolled-back savepoint."""
        try:
            return self._reserve_stock_for_order(order)
        except Exception as exc:
            self._record_stock_error(order, exc)
            raise

    @transaction.atomic
    def _reserve_stock_for_order(self, order: Order) -> Order:
        from bfg.delivery.models import Warehouse
        from bfg.shop.models import Product, ProductVariant, VariantInventory, OrderItemStockReservation
        from bfg.shop.services.inventory_service import InventoryService
        self.validate_workspace_access(order)
        order = Order.all_objects.select_for_update().get(pk=order.pk, workspace=self.workspace)
        if order.stock_deducted_at:
            return order
        if order.status in ('cancelled', 'refunded') or order.payment_status == 'refunded':
            raise ValueError('Order was cancelled or refunded; reconcile it manually.')
        items = list(order.items.select_related('product', 'variant').order_by('product_id', 'pk'))
        if not order.stock_reservations_managed and any(item.variant_id and item.product.track_inventory for item in items):
            raise ValueError('Legacy stock reservation has no recorded warehouse; reconcile this order manually.')
        warehouse = None
        inventory_service = InventoryService(self.workspace, self.user)
        for item in items:
            product = Product.all_objects.select_for_update().get(pk=item.product_id, workspace=self.workspace)
            if not product.track_inventory or not item.variant_id:
                continue
            variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id, product=product)
            reservation = OrderItemStockReservation.objects.select_for_update().filter(item=item).first()
            if reservation:
                if (reservation.quantity != item.quantity or reservation.inventory.variant_id != variant.pk or
                        reservation.inventory.warehouse.workspace_id != self.workspace.pk):
                    raise ValueError('Order stock reservation no longer matches its item; reconcile manually.')
                if reservation.state != 'reserved':
                    raise ValueError('Order stock reservation was already consumed or released; reconcile manually.')
                continue
            if warehouse is None:
                warehouse = Warehouse.all_objects.filter(workspace=self.workspace, is_active=True).order_by('-is_default', 'name').first()
            if warehouse is None:
                raise ValueError('Configure an active warehouse before reserving stock.')
            inventory = inventory_service.get_variant_inventory(variant, warehouse)
            inventory = VariantInventory.objects.select_for_update().get(pk=inventory.pk)
            inventory_service.reserve_stock(variant, warehouse, item.quantity)
            OrderItemStockReservation.objects.create(item=item, inventory=inventory, quantity=item.quantity)
        order.stock_reservations_managed = True
        order.stock_error = ''
        order.save(update_fields=['stock_reservations_managed', 'stock_error', 'updated_at'])
        return order

    def deduct_stock(self, order: Order) -> Order:
        """Deduct once independently of payment, consuming only this order's reservations."""
        try:
            return self._deduct_stock(order)
        except Exception as exc:
            self._record_stock_error(order, exc)
            raise

    @transaction.atomic
    def _deduct_stock(self, order: Order) -> Order:
        self.validate_workspace_access(order)
        order = Order.all_objects.select_for_update().get(pk=order.pk, workspace=self.workspace)
        if order.stock_deducted_at:
            return order
        order = self._reserve_stock_for_order(order)
        from bfg.delivery.models import Warehouse
        from bfg.shop.models import Product, ProductVariant, VariantInventory, OrderItemStockReservation
        from bfg.shop.services.inventory_service import InventoryService
        from bfg.core.events import after_commit
        inventory_service = InventoryService(self.workspace, self.user)
        for item in order.items.select_related('product', 'variant').order_by('product_id', 'pk'):
            product = Product.all_objects.select_for_update().get(pk=item.product_id, workspace=self.workspace)
            if not product.track_inventory:
                continue
            if item.variant_id:
                variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id, product=product)
                reservation = OrderItemStockReservation.objects.select_for_update().select_related('inventory__warehouse').get(item=item)
                inventory = VariantInventory.objects.select_for_update().get(pk=reservation.inventory_id)
                if reservation.state != 'reserved' or reservation.quantity != item.quantity or inventory.reserved < item.quantity:
                    raise ValueError('Owned stock reservation is inconsistent; reconcile the order.')
                if inventory.quantity < item.quantity:
                    raise ValueError('Insufficient variant stock; reconcile the order.')
                before = variant.stock_quantity
                inventory_service.fulfill_reservation(variant, reservation.inventory.warehouse, item.quantity)
                variant.refresh_from_db()
                if variant.stock_quantity != before - item.quantity:
                    raise ValueError('Existing order inventory update did not complete.')
                reservation.state = 'consumed'
                reservation.consumed_at = timezone.now()
                reservation.save(update_fields=['state', 'consumed_at'])
            else:
                if not Warehouse.all_objects.filter(workspace=self.workspace, is_active=True).exists():
                    raise ValueError('Configure an active warehouse before deducting stock.')
                if product.stock_quantity < item.quantity:
                    raise ValueError('Insufficient stock; reconcile this order.')
                Product.all_objects.filter(pk=product.pk, workspace=self.workspace).update(stock_quantity=F('stock_quantity') - item.quantity)
        order.stock_deducted_at = timezone.now()
        order.stock_error = ''
        order.save(update_fields=['stock_deducted_at', 'stock_error', 'updated_at'])
        after_commit(self.emit_event, 'order.stock_deducted', {'order': order})
        return order

    @transaction.atomic
    def release_stock_reservations(self, order: Order) -> Order:
        """Release owned, unconsumed reservations; never put deducted goods back into stock."""
        from bfg.shop.models import OrderItemStockReservation, VariantInventory
        from bfg.shop.services.inventory_service import InventoryService
        self.validate_workspace_access(order)
        order = Order.all_objects.select_for_update().get(pk=order.pk, workspace=self.workspace)
        inventory_service = InventoryService(self.workspace, self.user)
        reservations = OrderItemStockReservation.objects.select_for_update().filter(item__order=order, state='reserved').select_related('inventory__warehouse')
        for reservation in reservations:
            inventory = VariantInventory.objects.select_for_update().get(pk=reservation.inventory_id)
            if inventory.warehouse.workspace_id != self.workspace.pk or inventory.reserved < reservation.quantity:
                raise ValueError('Owned stock reservation is inconsistent; reconcile the order.')
            inventory_service.release_reservation(inventory.variant, inventory.warehouse, reservation.quantity)
            reservation.state = 'released'
            reservation.released_at = timezone.now()
            reservation.save(update_fields=['state', 'released_at'])
        if not order.stock_reservations_managed and order.items.filter(variant__isnull=False, product__track_inventory=True).exists():
            order.stock_error = 'Legacy stock reservation has no recorded warehouse; release it manually after reconciliation.'
            order.save(update_fields=['stock_error', 'updated_at'])
        return order

    @transaction.atomic
    def mark_as_paid(self, order: Order, *, update_inventory: bool = True) -> Order:
        """
        Mark payment confirmed, applying the order stock policy when requested
        
        Args:
            order: Order instance
            
        Returns:
            Order: Updated order instance
        """
        self.validate_workspace_access(order)
        order = Order.all_objects.select_for_update().get(
            pk=order.pk,
            workspace=self.workspace,
        )
        if order.payment_status == 'paid':
            return order
        
        old_payment_status = order.payment_status
        order.payment_status = 'paid'
        order.paid_at = timezone.now()
        order.save()
        
        # Channel imports can settle payment separately after applying their snapshotted stock policy.
        if update_inventory and order.stock_deduction_event == 'payment_confirmed':
            try:
                order = self.deduct_stock(order)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('Inventory deduction failed for order %s: %s', order.pk, exc)
                order.refresh_from_db(fields=['stock_error'])

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
    
    @transaction.atomic
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
        
        order = self.release_stock_reservations(order)
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

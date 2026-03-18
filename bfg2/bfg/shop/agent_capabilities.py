# -*- coding: utf-8 -*-
"""
Agent capabilities for shop.

Includes order lookup by order number, order detail retrieval, and targeted
order item quantity updates so the AI can work with business identifiers
such as order numbers and SKUs instead of only internal IDs.
"""
from decimal import Decimal

from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.shop.models import Order
from bfg.shop.services.order_service import OrderService
from bfg.shop.services.product_price_service import ProductPriceService


def _get_order_for_workspace(workspace, *, order_id: int = None, order_number: str = None):
    if order_id is not None:
        return Order.objects.get(id=order_id, workspace=workspace)
    if order_number:
        return Order.objects.get(order_number=order_number, workspace=workspace)
    raise ValueError("Provide order_id or order_number")


def _serialize_order_items(order):
    items = order.items.select_related("product", "variant").all().order_by("id")
    return [
        {
            "order_item_id": item.id,
            "product_id": item.product_id,
            "variant_id": item.variant_id,
            "sku": item.sku,
            "product_name": item.product_name,
            "variant_name": item.variant_name,
            "quantity": item.quantity,
            "price": str(item.price),
            "subtotal": str(item.subtotal),
        }
        for item in items
    ]


def _get_order_status_handler(request, *, order_id: int, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    order = Order.objects.get(id=order_id, workspace=workspace)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "total": str(order.total),
        "customer_id": order.customer_id,
    }


def _cancel_order_handler(request, *, order_id: int, reason: str = "", **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    order = Order.objects.get(id=order_id, workspace=workspace)
    service = OrderService(workspace=workspace, user=request.user)
    order = service.cancel_order(order, reason=reason)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
    }


def _update_product_price_handler(request, *, product_id: int, price: float, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    from bfg.shop.models import Product
    product = Product.objects.get(id=product_id, workspace=workspace)
    service = ProductPriceService(workspace=workspace, user=request.user)
    from django.utils import timezone
    service.schedule_price_change(
        product,
        new_price=Decimal(str(price)),
        effective_at=timezone.now(),
        changed_by=request.user,
        reason="Agent update",
    )
    product.refresh_from_db()
    return {
        "product_id": product.id,
        "price": str(product.price),
    }


def _get_order_by_number_handler(request, *, order_number: str, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    order = _get_order_for_workspace(workspace, order_number=order_number)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "total": str(order.total),
        "customer_id": order.customer_id,
        "items_summary": _serialize_order_items(order),
    }


def _get_order_detail_handler(
    request,
    *,
    order_id: int = None,
    order_number: str = None,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    order = _get_order_for_workspace(workspace, order_id=order_id, order_number=order_number)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "customer_id": order.customer_id,
        "subtotal": str(order.subtotal),
        "shipping_cost": str(order.shipping_cost),
        "discount": str(order.discount),
        "tax": str(order.tax),
        "total": str(order.total),
        "items": _serialize_order_items(order),
    }


def _create_order_handler(
    request,
    *,
    customer_id: int,
    store_id: int,
    shipping_address_id: int,
    billing_address_id: int = None,
    order_items: list = None,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    from bfg.common.models import Customer, Address
    from bfg.shop.models import Store, Product
    customer = Customer.objects.get(id=customer_id, workspace=workspace)
    store = Store.objects.get(id=store_id, workspace=workspace)
    shipping_address = Address.objects.get(id=shipping_address_id, workspace=workspace)
    billing_address = None
    if billing_address_id:
        billing_address = Address.objects.get(id=billing_address_id, workspace=workspace)
    items = order_items or []
    if not items:
        raise ValueError("order_items is required (e.g. [{ product_id: 1, quantity: 2 }])")
    subtotal = Decimal("0")
    order_items_data = []
    for row in items:
        pid = row.get("product_id")
        qty = int(row.get("quantity", 1))
        if not pid:
            continue
        product = Product.objects.get(id=pid, workspace=workspace)
        price = product.price
        if isinstance(row.get("price"), (int, float)):
            price = Decimal(str(row["price"]))
        item_subtotal = price * qty
        subtotal += item_subtotal
        order_items_data.append({
            "product_id": pid,
            "variant_id": row.get("variant_id"),
            "quantity": qty,
            "price": price,
            "subtotal": item_subtotal,
        })
    total = subtotal + kwargs.get("shipping_cost", Decimal("0")) + kwargs.get("tax", Decimal("0")) - kwargs.get("discount", Decimal("0"))
    service = OrderService(workspace=workspace, user=request.user)
    order = service.create_order(
        customer=customer,
        store=store,
        shipping_address=shipping_address,
        billing_address=billing_address,
        subtotal=subtotal,
        total=total,
        shipping_cost=kwargs.get("shipping_cost", Decimal("0")),
        tax=kwargs.get("tax", Decimal("0")),
        discount=kwargs.get("discount", Decimal("0")),
        order_items=order_items_data,
    )
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
    }


def _update_order_handler(
    request,
    *,
    order_id: int,
    shipping_address_id: int = None,
    billing_address_id: int = None,
    customer_note: str = None,
    admin_note: str = None,
    coupon_code: str = None,
    freight_service_id: int = None,
    order_items: list = None,
    **kwargs
):
    """
    Update order information before payment and shipment.

    Allows modification of order details including addresses, notes, coupon,
    freight service, and order items when the order is still pending payment
    and has not been shipped yet.
    """
    from django.db import transaction
    from bfg.common.models import Address
    from bfg.shop.models import Product, ProductVariant, OrderItem
    from bfg.delivery.models import FreightService
    from bfg.marketing.models import Coupon
    from django.utils import timezone

    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")

    # Get order and verify it belongs to workspace
    order = Order.objects.select_related('freight_service', 'coupon').get(
        id=order_id,
        workspace=workspace
    )

    # Validation: Check payment status
    if order.payment_status != "pending":
        raise ValueError("Order has been paid and cannot be modified")

    # Validation: Check order status
    if order.status not in ["pending", "processing"]:
        raise ValueError(f"Order in status {order.status} cannot be modified")

    updated_fields = []

    with transaction.atomic():
        # Update shipping address
        if shipping_address_id is not None:
            shipping_address = Address.objects.get(
                id=shipping_address_id,
                workspace=workspace
            )
            order.shipping_address = shipping_address
            updated_fields.append("shipping_address_id")

        # Update billing address
        if billing_address_id is not None:
            billing_address = Address.objects.get(
                id=billing_address_id,
                workspace=workspace
            )
            order.billing_address = billing_address
            updated_fields.append("billing_address_id")

        # Update customer note
        if customer_note is not None:
            order.customer_note = customer_note
            updated_fields.append("customer_note")

        # Update admin note
        if admin_note is not None:
            order.admin_note = admin_note
            updated_fields.append("admin_note")

        # Update freight service and recalculate shipping cost
        if freight_service_id is not None:
            freight_service = FreightService.objects.get(
                id=freight_service_id,
                workspace=workspace
            )
            order.freight_service = freight_service
            # Simple shipping cost update - use freight service base cost
            if hasattr(freight_service, 'base_cost'):
                order.shipping_cost = freight_service.base_cost
            updated_fields.append("freight_service_id")
            updated_fields.append("shipping_cost")

        # Update coupon and recalculate discount
        if coupon_code is not None:
            if coupon_code == "":
                # Remove coupon
                order.coupon = None
                order.discount = Decimal("0")
                updated_fields.append("coupon_code")
                updated_fields.append("discount")
            else:
                # Apply new coupon
                try:
                    coupon = Coupon.objects.select_related('discount_rule').get(
                        code=coupon_code,
                        workspace=workspace,
                        is_active=True,
                        valid_from__lte=timezone.now()
                    )
                    # Check if coupon is expired
                    if coupon.valid_until and coupon.valid_until < timezone.now():
                        raise ValueError(f"Coupon '{coupon_code}' has expired")

                    order.coupon = coupon

                    # Simple discount calculation
                    discount_rule = coupon.discount_rule
                    if discount_rule.discount_type == 'percentage':
                        discount_amount = order.subtotal * (discount_rule.discount_value / Decimal("100"))
                        if discount_rule.maximum_discount:
                            discount_amount = min(discount_amount, discount_rule.maximum_discount)
                        order.discount = discount_amount
                    elif discount_rule.discount_type == 'fixed_amount':
                        order.discount = discount_rule.discount_value
                    elif discount_rule.discount_type == 'free_shipping':
                        order.discount = order.shipping_cost

                    updated_fields.append("coupon_code")
                    updated_fields.append("discount")
                except Coupon.DoesNotExist:
                    raise ValueError(f"Coupon '{coupon_code}' does not exist or is not active")

        # Update order items and recalculate subtotal
        if order_items is not None:
            # Validate order items
            for item_data in order_items:
                quantity = item_data.get("quantity", 0)
                if quantity < 1:
                    raise ValueError(f"Quantity must be >= 1, got {quantity}")

                price = item_data.get("price")
                if price is not None and price < 0:
                    raise ValueError(f"Price must be >= 0, got {price}")

            # Delete all existing items
            OrderItem.objects.filter(order=order).delete()

            # Create new items and calculate subtotal
            subtotal = Decimal("0")
            for item_data in order_items:
                product_id = item_data.get("product_id")
                variant_id = item_data.get("variant_id")
                quantity = int(item_data.get("quantity", 1))
                price = item_data.get("price")

                # Get product
                product = Product.objects.get(id=product_id, workspace=workspace)

                # Get variant if specified
                variant = None
                if variant_id:
                    variant = ProductVariant.objects.get(
                        id=variant_id,
                        product=product
                    )

                # Use specified price or product/variant price
                if price is None:
                    if variant:
                        price = variant.price if hasattr(variant, 'price') else product.price
                    else:
                        price = product.price
                else:
                    price = Decimal(str(price))

                item_subtotal = price * quantity
                subtotal += item_subtotal

                # Create order item
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    variant=variant,
                    product_name=product.name,
                    variant_name=variant.name if variant and hasattr(variant, 'name') else "",
                    sku=variant.sku if variant and hasattr(variant, 'sku') else product.sku if hasattr(product, 'sku') else "",
                    quantity=quantity,
                    price=price,
                    subtotal=item_subtotal
                )

            order.subtotal = subtotal
            updated_fields.append("order_items")
            updated_fields.append("subtotal")

        # Recalculate total
        if any(field in updated_fields for field in ["subtotal", "shipping_cost", "discount"]):
            order.total = order.subtotal + order.shipping_cost + order.tax - order.discount
            if "total" not in updated_fields:
                updated_fields.append("total")

        # Save order with updated fields
        save_fields = []
        field_mapping = {
            "shipping_address_id": "shipping_address",
            "billing_address_id": "billing_address",
            "customer_note": "customer_note",
            "admin_note": "admin_note",
            "freight_service_id": "freight_service",
            "shipping_cost": "shipping_cost",
            "coupon_code": "coupon",
            "discount": "discount",
            "subtotal": "subtotal",
            "total": "total",
        }

        for field in updated_fields:
            if field in field_mapping:
                save_fields.append(field_mapping[field])

        if save_fields:
            save_fields.append("updated_at")
            order.save(update_fields=list(set(save_fields)))

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "subtotal": str(order.subtotal),
        "shipping_cost": str(order.shipping_cost),
        "discount": str(order.discount),
        "tax": str(order.tax),
        "total": str(order.total),
        "updated_fields": updated_fields,
    }


def _update_order_item_quantity_handler(
    request,
    *,
    quantity: int,
    order_id: int = None,
    order_number: str = None,
    order_item_id: int = None,
    sku: str = None,
    product_id: int = None,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    order = _get_order_for_workspace(workspace, order_id=order_id, order_number=order_number)
    existing_items = list(order.items.select_related("product", "variant").all().order_by("id"))
    if not existing_items:
        raise ValueError("Order has no items")

    matches = []
    if order_item_id is not None:
        matches = [item for item in existing_items if item.id == order_item_id]
    elif sku:
        sku_normalized = sku.strip().lower()
        matches = [
            item for item in existing_items
            if (
                (item.sku or "").strip().lower() == sku_normalized
                or (item.product_name or "").strip().lower() == sku_normalized
                or (item.variant_name or "").strip().lower() == sku_normalized
            )
        ]
    elif product_id is not None:
        matches = [item for item in existing_items if item.product_id == product_id]
    else:
        raise ValueError("Provide order_item_id, sku, or product_id")

    if not matches:
        raise ValueError("No matching order item found in the order")
    if len(matches) > 1:
        raise ValueError("Multiple order items matched. Provide order_item_id for an exact match")

    target = matches[0]
    rebuilt_items = []
    for item in existing_items:
        rebuilt_items.append({
            "product_id": item.product_id,
            "variant_id": item.variant_id,
            "quantity": quantity if item.id == target.id else item.quantity,
            "price": float(item.price),
        })

    result = _update_order_handler(
        request,
        order_id=order.id,
        order_items=rebuilt_items,
    )
    result["updated_item"] = {
        "order_item_id": target.id,
        "product_id": target.product_id,
        "variant_id": target.variant_id,
        "sku": target.sku,
        "product_name": target.product_name,
        "variant_name": target.variant_name,
        "quantity": quantity,
    }
    return result


# Read-only order lookup is covered by API: GET /orders/?order_number=..., GET /orders/{id}/
CAPABILITIES = [
    AgentCapability(
        id="shop.cancel_order",
        name="Cancel order",
        description="Cancel an order. Optional reason.",
        app_label="shop",
        input_schema={
            "type": "object",
            "required": ["order_id"],
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "reason": {"type": "string", "description": "Cancellation reason"},
            },
        },
        handler=_cancel_order_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="shop.update_product_price",
        name="Update product price",
        description="Update the price of a product (effective immediately).",
        app_label="shop",
        input_schema={
            "type": "object",
            "required": ["product_id", "price"],
            "properties": {
                "product_id": {"type": "integer", "description": "Product ID"},
                "price": {"type": "number", "description": "New price"},
            },
        },
        handler=_update_product_price_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="shop.create_order",
        name="Create order",
        description="Create an order for a customer (customer_id, store_id, shipping_address_id, order_items).",
        app_label="shop",
        input_schema={
            "type": "object",
            "required": ["customer_id", "store_id", "shipping_address_id", "order_items"],
            "properties": {
                "customer_id": {"type": "integer", "description": "Customer ID"},
                "store_id": {"type": "integer", "description": "Store ID"},
                "shipping_address_id": {"type": "integer", "description": "Shipping address ID"},
                "billing_address_id": {"type": "integer", "description": "Billing address ID (optional)"},
                "order_items": {
                    "type": "array",
                    "description": "List of { product_id, quantity, price? }",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "integer"},
                            "variant_id": {"type": "integer"},
                            "quantity": {"type": "integer"},
                            "price": {"type": "number"},
                        },
                    },
                },
                "shipping_cost": {"type": "number"},
                "tax": {"type": "number"},
                "discount": {"type": "number"},
            },
        },
        handler=_create_order_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="shop.update_order",
        name="Update order",
        description="Update order information (addresses, notes, coupon, freight service, order items) before payment and shipment.",
        app_label="shop",
        input_schema={
            "type": "object",
            "required": ["order_id"],
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "shipping_address_id": {"type": "integer", "description": "New shipping address ID"},
                "billing_address_id": {"type": "integer", "description": "New billing address ID"},
                "customer_note": {"type": "string", "description": "Customer note"},
                "admin_note": {"type": "string", "description": "Admin note"},
                "coupon_code": {"type": "string", "description": "Coupon code to apply (empty string to remove)"},
                "freight_service_id": {"type": "integer", "description": "Freight service ID"},
                "order_items": {
                    "type": "array",
                    "description": "Order items to set. If provided, replaces ALL items. Each item: { product_id, quantity, variant_id?, price?, order_item_id? }",
                    "items": {
                        "type": "object",
                        "required": ["product_id", "quantity"],
                        "properties": {
                            "order_item_id": {"type": "integer"},
                            "product_id": {"type": "integer"},
                            "variant_id": {"type": "integer"},
                            "quantity": {"type": "integer", "minimum": 1},
                            "price": {"type": "number", "minimum": 0},
                        },
                    },
                },
            },
        },
        handler=_update_order_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="shop.update_order_item_quantity",
        name="Update order item quantity",
        description="Update the quantity of a single order item using order_item_id, SKU, product code/name, or product_id within an order.",
        app_label="shop",
        input_schema={
            "type": "object",
            "required": ["quantity"],
            "properties": {
                "order_id": {"type": "integer", "description": "Internal order ID"},
                "order_number": {"type": "string", "description": "Business order number"},
                "order_item_id": {"type": "integer", "description": "Exact order item ID"},
                "sku": {"type": "string", "description": "Order item SKU, product code, or exact item name"},
                "product_id": {"type": "integer", "description": "Product ID if unique within the order"},
                "quantity": {"type": "integer", "minimum": 1, "description": "New quantity"},
            },
        },
        handler=_update_order_item_quantity_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

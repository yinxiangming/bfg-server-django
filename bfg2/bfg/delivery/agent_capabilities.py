# -*- coding: utf-8 -*-
"""
Agent capabilities for delivery: ship_order, get_shipping_options.
Handlers delegate to DeliveryService / existing view logic; required_permission = IsWorkspaceStaff.
"""
from bfg.common.models import Address
from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.delivery.models import Carrier, FreightService, Warehouse
from bfg.delivery.services import DeliveryService
from bfg.shop.models import Order


def _ship_order_handler(request, *, order_id: int, carrier_id: int, service_code: str, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    order = Order.objects.get(id=order_id, workspace=workspace)
    carrier = Carrier.objects.get(id=carrier_id, workspace=workspace)
    warehouse = Warehouse.objects.filter(
        workspace=workspace, is_default=True, is_active=True
    ).first() or Warehouse.objects.filter(workspace=workspace, is_active=True).first()
    if not warehouse:
        raise ValueError("No warehouse configured")
    sender_address, _ = Address.objects.get_or_create(
        workspace=workspace,
        full_name=warehouse.name,
        address_line1=warehouse.address_line1,
        city=warehouse.city,
        postal_code=warehouse.postal_code,
        country=warehouse.country or "NZ",
        defaults={
            "address_line2": warehouse.address_line2 or "",
            "state": warehouse.state or "",
            "phone": warehouse.phone or "",
            "email": warehouse.email or "",
        },
    )
    recipient_address = order.shipping_address
    if not recipient_address:
        raise ValueError("Order has no shipping address")
    freight_service = FreightService.objects.filter(
        carrier=carrier, code=service_code, is_active=True
    ).first() or FreightService.objects.filter(carrier=carrier, is_active=True).first()
    if not freight_service:
        raise ValueError(f"No freight service configured for carrier {carrier.name}")
    delivery_service = DeliveryService(workspace=workspace, user=request.user)
    consignment = delivery_service.create_consignment(
        orders=[order],
        service=freight_service,
        sender_address=sender_address,
        recipient_address=recipient_address,
    )
    ship_result = delivery_service.ship_consignment(
        consignment=consignment, service_code=service_code
    )
    if not ship_result.get("success"):
        return {
            "success": False,
            "consignment_number": consignment.consignment_number,
            "error": ship_result.get("error", "Failed to create shipment with carrier"),
        }
    consignment.refresh_from_db()
    return {
        "success": True,
        "consignment_id": consignment.id,
        "consignment_number": consignment.consignment_number,
        "tracking_number": consignment.tracking_number,
        "label_url": ship_result.get("label_url", ""),
        "carrier_name": carrier.name,
        "service_code": service_code,
    }


# delivery.get_shipping_options removed: use API POST /carriers/{id}/get_shipping_options/

CAPABILITIES = [
    AgentCapability(
        id="delivery.ship_order",
        name="Ship order",
        description="Create consignment and ship an order with a carrier and service code.",
        app_label="delivery",
        input_schema={
            "type": "object",
            "required": ["order_id", "carrier_id", "service_code"],
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
                "carrier_id": {"type": "integer", "description": "Carrier ID"},
                "service_code": {"type": "string", "description": "Freight service code"},
            },
        },
        handler=_ship_order_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

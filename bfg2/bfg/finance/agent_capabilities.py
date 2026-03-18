# -*- coding: utf-8 -*-
"""
Agent capabilities for finance: create_invoice, get_payout_summary, process_refund.
Handlers delegate to InvoiceService / PaymentService; required_permission = IsWorkspaceStaff.
"""
from decimal import Decimal

from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.finance.models import Payment
from bfg.finance.services import InvoiceService, PaymentService
from bfg.shop.models import Order


def _create_invoice_handler(request, *, order_id: int, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    order = Order.objects.get(id=order_id, workspace=workspace)
    from bfg.common.constants import get_default_currency_for_workspace
    from bfg.finance.models import Currency
    code = get_default_currency_for_workspace(workspace)
    currency = Currency.objects.filter(code=code, is_active=True).first() or Currency.objects.filter(is_active=True).first()
    if not currency:
        raise ValueError("No active currency configured")
    service = InvoiceService(workspace=workspace, user=request.user)
    invoice = service.create_invoice_from_order(order, currency)
    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "order_id": order_id,
        "status": invoice.status,
        "total": str(invoice.total),
    }


def _process_refund_handler(request, *, payment_id: int, amount: float, reason: str = "", **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    payment = Payment.objects.get(id=payment_id, workspace=workspace)
    service = PaymentService(workspace=workspace, user=request.user)
    refund = service.create_refund(payment, amount=Decimal(str(amount)), reason=reason)
    return {
        "refund_id": refund.id,
        "payment_id": payment_id,
        "amount": str(refund.amount),
        "status": refund.status,
    }


CAPABILITIES = [
    AgentCapability(
        id="finance.create_invoice",
        name="Create invoice from order",
        description="Create an invoice for an existing order.",
        app_label="finance",
        input_schema={
            "type": "object",
            "required": ["order_id"],
            "properties": {
                "order_id": {"type": "integer", "description": "Order ID"},
            },
        },
        handler=_create_invoice_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    # finance.get_payout_summary removed: use API GET /wallets/ and aggregate or GET /withdrawal-requests/
    AgentCapability(
        id="finance.process_refund",
        name="Process refund",
        description="Process a refund for a payment (payment_id, amount, optional reason).",
        app_label="finance",
        input_schema={
            "type": "object",
            "required": ["payment_id", "amount"],
            "properties": {
                "payment_id": {"type": "integer", "description": "Payment ID"},
                "amount": {"type": "number", "description": "Refund amount"},
                "reason": {"type": "string", "description": "Refund reason"},
            },
        },
        handler=_process_refund_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

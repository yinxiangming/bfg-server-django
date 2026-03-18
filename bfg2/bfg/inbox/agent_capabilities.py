# -*- coding: utf-8 -*-
"""
Agent capabilities for inbox: send_message, mark_conversation_read.
Handlers delegate to MessageService; required_permission = IsWorkspaceStaff.
"""
from django.utils import timezone

from bfg.common.models import Customer
from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.inbox.models import MessageRecipient
from bfg.inbox.services import MessageService


def _send_message_handler(
    request,
    *,
    subject: str,
    message: str,
    recipient_customer_ids: list,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    if not recipient_customer_ids:
        raise ValueError("recipient_customer_ids is required (list of customer IDs)")
    recipients = list(
        Customer.objects.filter(
            id__in=recipient_customer_ids,
            workspace=workspace,
        )
    )
    if len(recipients) != len(recipient_customer_ids):
        raise ValueError("Some customer IDs not found in workspace")
    service = MessageService(workspace=workspace, user=request.user)
    msg = service.send_message(
        recipients=recipients,
        subject=subject or "Message",
        message=message or "",
    )
    return {
        "message_id": msg.id,
        "subject": msg.subject,
        "recipient_count": len(recipients),
    }


def _mark_conversation_read_handler(request, *, customer_id: int, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    customer = Customer.objects.get(id=customer_id, workspace=workspace)
    updated = MessageRecipient.objects.filter(
        recipient=customer,
        is_deleted=False,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())
    return {
        "customer_id": customer_id,
        "updated_count": updated,
    }


CAPABILITIES = [
    AgentCapability(
        id="inbox.send_message",
        name="Send message",
        description="Send an in-app message to one or more customers (subject, message, recipient_customer_ids).",
        app_label="inbox",
        input_schema={
            "type": "object",
            "required": ["subject", "message", "recipient_customer_ids"],
            "properties": {
                "subject": {"type": "string", "description": "Message subject"},
                "message": {"type": "string", "description": "Message body"},
                "recipient_customer_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of customer IDs",
                },
            },
        },
        handler=_send_message_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="inbox.mark_conversation_read",
        name="Mark conversation read",
        description="Mark all messages as read for a customer.",
        app_label="inbox",
        input_schema={
            "type": "object",
            "required": ["customer_id"],
            "properties": {
                "customer_id": {"type": "integer", "description": "Customer ID"},
            },
        },
        handler=_mark_conversation_read_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

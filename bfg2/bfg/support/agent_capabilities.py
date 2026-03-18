# -*- coding: utf-8 -*-
"""
Agent capabilities for support: close_ticket, reply_ticket, assign_ticket.
Handlers replicate view logic; required_permission = IsWorkspaceStaff.
"""
from django.utils import timezone
from django.db import transaction

from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.support.models import SupportTicket, SupportTicketMessage, TicketAssignment


def _get_ticket(request, ticket_id: int) -> SupportTicket:
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    return SupportTicket.objects.get(id=ticket_id, workspace=workspace)


def _close_ticket_handler(request, *, ticket_id: int, **kwargs):
    ticket = _get_ticket(request, ticket_id)
    ticket.status = "closed"
    ticket.closed_at = timezone.now()
    ticket.save()
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "status": ticket.status,
        "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
    }


def _reply_ticket_handler(
    request, *, ticket_id: int, message: str, is_internal: bool = False, **kwargs
):
    ticket = _get_ticket(request, ticket_id)
    message_text = (message or "").strip()
    if not message_text:
        raise ValueError("message is required")
    with transaction.atomic():
        SupportTicketMessage.objects.create(
            ticket=ticket,
            message=message_text,
            is_staff_reply=True,
            is_internal=bool(is_internal),
            sender=request.user,
        )
        if not ticket.first_response_at:
            ticket.first_response_at = timezone.now()
        if ticket.status == "new":
            ticket.status = "open"
        ticket.save(update_fields=["first_response_at", "status", "updated_at"])
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "status": ticket.status,
    }


def _assign_ticket_handler(request, *, ticket_id: int, assigned_to_id: int, **kwargs):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    ticket = _get_ticket(request, ticket_id)
    user = User.objects.get(id=assigned_to_id)
    old_id = ticket.assigned_to_id
    with transaction.atomic():
        ticket.assigned_to = user
        ticket.save(update_fields=["assigned_to", "updated_at"])
        if old_id != user.id:
            TicketAssignment.objects.create(
                ticket=ticket,
                assigned_from_id=old_id,
                assigned_to=user,
                assigned_by=request.user,
            )
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "assigned_to_id": user.id,
    }


CAPABILITIES = [
    AgentCapability(
        id="support.close_ticket",
        name="Close ticket",
        description="Close a support ticket by id.",
        app_label="support",
        input_schema={
            "type": "object",
            "required": ["ticket_id"],
            "properties": {
                "ticket_id": {"type": "integer", "description": "Support ticket ID"},
            },
        },
        handler=_close_ticket_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="support.reply_ticket",
        name="Reply to ticket",
        description="Add a staff reply to a support ticket.",
        app_label="support",
        input_schema={
            "type": "object",
            "required": ["ticket_id", "message"],
            "properties": {
                "ticket_id": {"type": "integer", "description": "Support ticket ID"},
                "message": {"type": "string", "description": "Reply message content"},
                "is_internal": {
                    "type": "boolean",
                    "description": "If true, reply is internal (not visible to customer)",
                    "default": False,
                },
            },
        },
        handler=_reply_ticket_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="support.assign_ticket",
        name="Assign ticket",
        description="Assign a support ticket to a user by user id.",
        app_label="support",
        input_schema={
            "type": "object",
            "required": ["ticket_id", "assigned_to_id"],
            "properties": {
                "ticket_id": {"type": "integer", "description": "Support ticket ID"},
                "assigned_to_id": {"type": "integer", "description": "User ID to assign the ticket to"},
            },
        },
        handler=_assign_ticket_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

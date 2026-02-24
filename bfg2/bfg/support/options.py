from typing import Dict, Any

from .models import TicketPriority, TicketCategory, SupportTicket


def get_options(workspace) -> Dict[str, Any]:
    """
    Return support module options for the given workspace.
    """
    priorities = TicketPriority.objects.filter(workspace=workspace, is_active=True).order_by("level")
    categories = TicketCategory.objects.filter(workspace=workspace, is_active=True).order_by("order", "name")

    return {
        "ticket_statuses": [
            {"value": code, "label": label}
            for code, label in SupportTicket.STATUS_CHOICES
        ],
        "ticket_priorities": [
            {"value": p.id, "label": p.name, "level": p.level, "color": p.color}
            for p in priorities
        ],
        "ticket_categories": [
            {"value": c.id, "label": c.name, "order": c.order}
            for c in categories
        ],
    }


from typing import Dict, Any

from .models import TicketPriority, TicketCategory, SupportTicket


def get_options(workspace) -> Dict[str, Any]:
    """
    Return support module options for the given workspace.
    Includes support_notice (response time & contact info) from workspace settings for account support page.
    """
    priorities = TicketPriority.objects.filter(workspace=workspace, is_active=True).order_by("level")
    categories = TicketCategory.objects.filter(workspace=workspace, is_active=True).order_by("order", "name")

    support_notice = ""
    try:
        ws_settings = getattr(workspace, "workspace_settings", None)
        if ws_settings and getattr(ws_settings, "custom_settings", None):
            support_custom = (ws_settings.custom_settings or {}).get("support") or {}
            support_notice = (support_custom.get("notice") or "") if isinstance(support_custom, dict) else ""
    except Exception:
        pass

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
        "support_notice": support_notice,
    }


# -*- coding: utf-8 -*-
"""
Agent capabilities for common: update_workspace_settings, get_customer_info.
Handlers delegate to SettingsService / Customer model; required_permission = IsWorkspaceStaff.
"""
from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff
from bfg.common.services import SettingsService


ALLOWED_SETTINGS_KEYS = [
    "site_name", "site_description", "logo", "favicon",
    "default_language", "supported_languages", "default_currency",
    "default_timezone", "contact_email", "support_email",
    "contact_phone", "facebook_url", "twitter_url", "instagram_url",
    "features", "custom_settings",
]


def _update_workspace_settings_handler(request, *, settings: dict = None, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    updates = dict(settings or {}, **kwargs)
    updates = {k: v for k, v in updates.items() if k in ALLOWED_SETTINGS_KEYS and v is not None}
    if not updates:
        raise ValueError("Provide settings (e.g. site_name, default_currency)")
    service = SettingsService(workspace=workspace, user=request.user)
    settings_obj = service.get_or_create_settings(workspace)
    settings_obj = service.update_settings(settings_obj, **updates)
    return {
        "updated": True,
        "site_name": getattr(settings_obj, "site_name", None),
        "default_currency": getattr(settings_obj, "default_currency", None),
    }


CAPABILITIES = [
    AgentCapability(
        id="common.update_workspace_settings",
        name="Update workspace settings",
        description="Update workspace settings (e.g. site_name, default_currency, contact_email).",
        app_label="common",
        input_schema={
            "type": "object",
            "required": [],
            "properties": {
                "site_name": {"type": "string"},
                "site_description": {"type": "string"},
                "default_currency": {"type": "string"},
                "default_language": {"type": "string"},
                "contact_email": {"type": "string"},
                "support_email": {"type": "string"},
                "contact_phone": {"type": "string"},
            },
        },
        handler=_update_workspace_settings_handler,
        required_permission=(IsWorkspaceAdmin,),
    ),
    # common.get_customer_info removed: use API GET /customers/{id}/
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

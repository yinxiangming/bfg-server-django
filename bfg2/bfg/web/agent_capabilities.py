# -*- coding: utf-8 -*-
"""
Agent capabilities for web: update_page_content, publish_page.
Handlers delegate to PageService; required_permission = IsWorkspaceStaff.
"""
from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.web.models import Page
from bfg.web.services import PageService


def _update_page_content_handler(
    request,
    *,
    page_id: int,
    title: str = None,
    content: str = None,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    page = Page.objects.get(id=page_id, workspace=workspace)
    service = PageService(workspace=workspace, user=request.user)
    updates = {}
    if title is not None:
        updates["title"] = title
    if content is not None:
        updates["content"] = content
    for k, v in kwargs.items():
        if hasattr(page, k) and k not in ("id", "workspace", "created_by", "created_at"):
            updates[k] = v
    if not updates:
        raise ValueError("Provide at least one of title, content")
    page = service.update_page(page, **updates)
    return {
        "page_id": page.id,
        "slug": page.slug,
        "title": page.title,
        "status": page.status,
    }


def _publish_page_handler(request, *, page_id: int, **kwargs):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    page = Page.objects.get(id=page_id, workspace=workspace)
    service = PageService(workspace=workspace, user=request.user)
    page = service.publish_page(page)
    return {
        "page_id": page.id,
        "slug": page.slug,
        "title": page.title,
        "status": page.status,
        "published_at": page.published_at.isoformat() if page.published_at else None,
    }


CAPABILITIES = [
    AgentCapability(
        id="web.update_page_content",
        name="Update page content",
        description="Update a CMS page (title, content, or other fields) by page ID.",
        app_label="web",
        input_schema={
            "type": "object",
            "required": ["page_id"],
            "properties": {
                "page_id": {"type": "integer", "description": "Page ID"},
                "title": {"type": "string", "description": "Page title"},
                "content": {"type": "string", "description": "Page body content (HTML/text)"},
            },
        },
        handler=_update_page_content_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="web.publish_page",
        name="Publish page",
        description="Publish a draft page by page ID.",
        app_label="web",
        input_schema={
            "type": "object",
            "required": ["page_id"],
            "properties": {
                "page_id": {"type": "integer", "description": "Page ID"},
            },
        },
        handler=_publish_page_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

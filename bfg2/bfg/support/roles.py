# -*- coding: utf-8 -*-
"""Support module role declarations + permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "support"

CRUD = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    role_registry.register_role(
        RoleDefinition(
            code="customer_service",
            name="Customer Service",
            description="Handle tickets and inquiries; read-only access to orders and customers.",
            default_permissions={
                "support.ticket": ["create", "read", "update"],
                "support.feedback": ["read", "update"],
                "shop.order": ["read"],
                "common.customer": ["read"],
            },
            owner_module=OWNER,
            sort_order=60,
        )
    )

    for sort, key, label in [
        (50, "support.ticket", "Tickets"),
        (51, "support.feedback", "Feedback"),
        (52, "support.knowledge_base", "Knowledge Base"),
    ]:
        role_registry.register_permission_module(
            PermissionModule(
                key=key,
                label=label,
                owner_module=OWNER,
                group="Support",
                actions=CRUD,
                sort_order=sort,
            )
        )

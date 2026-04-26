# -*- coding: utf-8 -*-
"""Common-module role declarations + foundational permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "common"

CRUD_ACTIONS = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    # ── Roles ────────────────────────────────────────────────────────
    role_registry.register_role(
        RoleDefinition(
            code="admin",
            name="Administrator",
            description="Full access to every workspace resource.",
            default_permissions={"*": ["create", "read", "update", "delete"]},
            owner_module=OWNER,
            sort_order=10,
        )
    )
    role_registry.register_role(
        RoleDefinition(
            code="manager",
            name="Manager",
            description="Power user across shop, delivery and CMS — but cannot manage staff, billing or workspace settings.",
            default_permissions={
                "shop.product": ["create", "read", "update", "delete"],
                "shop.category": ["create", "read", "update", "delete"],
                "shop.order": ["read", "update"],
                "delivery.warehouse": ["read", "update"],
                "delivery.consignment": ["create", "read", "update"],
                "web.page": ["create", "read", "update", "delete"],
                "web.post": ["create", "read", "update", "delete"],
            },
            owner_module=OWNER,
            sort_order=20,
        )
    )
    role_registry.register_role(
        RoleDefinition(
            code="staff",
            name="Staff",
            description="Read-only access to day-to-day operations data.",
            default_permissions={
                "shop.product": ["read"],
                "shop.order": ["read"],
                "delivery.consignment": ["read"],
            },
            owner_module=OWNER,
            sort_order=30,
        )
    )

    # ── Permission catalog (common-owned) ────────────────────────────
    role_registry.register_permission_module(
        PermissionModule(
            key="common.customer",
            label="Customers",
            owner_module=OWNER,
            group="Common",
            actions=CRUD_ACTIONS,
            sort_order=10,
        )
    )

# -*- coding: utf-8 -*-
"""Shop module role declarations + permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "shop"

CRUD = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    role_registry.register_role(
        RoleDefinition(
            code="store_admin",
            name="Store Administrator",
            description="Manage products, categories, store settings and orders.",
            default_permissions={
                "shop.store": ["read", "update"],
                "shop.product": ["create", "read", "update", "delete"],
                "shop.category": ["create", "read", "update", "delete"],
                "shop.order": ["read", "update"],
                "delivery.consignment": ["create", "read", "update"],
            },
            owner_module=OWNER,
            sort_order=40,
        )
    )

    for sort, key, label in [
        (20, "shop.store", "Stores"),
        (21, "shop.product", "Products"),
        (22, "shop.category", "Categories"),
        (23, "shop.order", "Orders"),
        (24, "shop.inventory", "Inventory"),
        (25, "shop.sales_channel", "Sales Channels"),
        (26, "shop.subscription_plan", "Subscription Plans"),
    ]:
        role_registry.register_permission_module(
            PermissionModule(
                key=key,
                label=label,
                owner_module=OWNER,
                group="Shop",
                actions=CRUD,
                sort_order=sort,
            )
        )

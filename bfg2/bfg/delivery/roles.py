# -*- coding: utf-8 -*-
"""Delivery module role declarations + permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "delivery"

CRUD = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    role_registry.register_role(
        RoleDefinition(
            code="warehouse_manager",
            name="Warehouse Manager",
            description="Manage warehouses, manifests and consignments. Read-only on stock.",
            default_permissions={
                "delivery.warehouse": ["read", "update"],
                "delivery.manifest": ["create", "read", "update"],
                "delivery.consignment": ["create", "read", "update"],
                "shop.inventory": ["read", "update"],
            },
            owner_module=OWNER,
            sort_order=50,
        )
    )

    for sort, key, label in [
        (30, "delivery.warehouse", "Warehouses"),
        (31, "delivery.manifest", "Manifests"),
        (32, "delivery.consignment", "Consignments"),
        (33, "delivery.carrier", "Carriers"),
        (34, "delivery.zone", "Delivery Zones"),
        (35, "delivery.freight_status", "Freight Statuses"),
    ]:
        role_registry.register_permission_module(
            PermissionModule(
                key=key,
                label=label,
                owner_module=OWNER,
                group="Delivery",
                actions=CRUD,
                sort_order=sort,
            )
        )

# -*- coding: utf-8 -*-
"""Finance module role declarations + permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "finance"

CRUD = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    role_registry.register_role(
        RoleDefinition(
            code="accountant",
            name="Accountant",
            description="Manage invoices, payments and tax rates; read-only on orders.",
            default_permissions={
                "finance.invoice": ["create", "read", "update"],
                "finance.payment": ["create", "read", "update"],
                "finance.tax_rate": ["read", "update"],
                "shop.order": ["read"],
            },
            owner_module=OWNER,
            sort_order=70,
        )
    )

    for sort, key, label in [
        (60, "finance.invoice", "Invoices"),
        (61, "finance.payment", "Payments"),
        (62, "finance.tax_rate", "Tax Rates"),
        (63, "finance.payment_gateway", "Payment Gateways"),
        (64, "finance.wallet", "Wallets"),
    ]:
        role_registry.register_permission_module(
            PermissionModule(
                key=key,
                label=label,
                owner_module=OWNER,
                group="Finance",
                actions=CRUD,
                sort_order=sort,
            )
        )

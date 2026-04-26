# -*- coding: utf-8 -*-
"""Marketing module role declarations + permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "marketing"

CRUD = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    role_registry.register_role(
        RoleDefinition(
            code="marketer",
            name="Marketer",
            description="Manage campaigns, coupons, referrals and gift cards.",
            default_permissions={
                "marketing.campaign": ["create", "read", "update", "delete"],
                "marketing.coupon": ["create", "read", "update", "delete"],
                "marketing.referral": ["read", "update"],
                "marketing.gift_card": ["create", "read", "update"],
            },
            owner_module=OWNER,
            sort_order=90,
        )
    )

    for sort, key, label in [
        (80, "marketing.campaign", "Campaigns"),
        (81, "marketing.coupon", "Coupons"),
        (82, "marketing.referral", "Referrals"),
        (83, "marketing.affiliate", "Affiliates"),
        (84, "marketing.gift_card", "Gift Cards"),
    ]:
        role_registry.register_permission_module(
            PermissionModule(
                key=key,
                label=label,
                owner_module=OWNER,
                group="Marketing",
                actions=CRUD,
                sort_order=sort,
            )
        )

# -*- coding: utf-8 -*-
"""Web/CMS module role declarations + permission catalog."""

from bfg.common.role_registry import (
    PermissionAction,
    PermissionModule,
    RoleDefinition,
    role_registry,
)

OWNER = "web"

CRUD = [
    PermissionAction("create", "Create"),
    PermissionAction("read", "Read"),
    PermissionAction("update", "Update"),
    PermissionAction("delete", "Delete"),
]


def register() -> None:
    role_registry.register_role(
        RoleDefinition(
            code="content_editor",
            name="Content Editor",
            description="Manage CMS pages, posts, media and menus.",
            default_permissions={
                "web.page": ["create", "read", "update", "delete"],
                "web.post": ["create", "read", "update", "delete"],
                "web.media": ["create", "read", "update", "delete"],
                "web.menu": ["read", "update"],
            },
            owner_module=OWNER,
            sort_order=80,
        )
    )

    for sort, key, label in [
        (70, "web.site", "Sites"),
        (71, "web.page", "Pages"),
        (72, "web.post", "Posts"),
        (73, "web.media", "Media"),
        (74, "web.menu", "Menus"),
        (75, "web.category", "CMS Categories"),
    ]:
        role_registry.register_permission_module(
            PermissionModule(
                key=key,
                label=label,
                owner_module=OWNER,
                group="CMS",
                actions=CRUD,
                sort_order=sort,
            )
        )

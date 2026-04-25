# -*- coding: utf-8 -*-
"""
Role provisioning

Materialises ``role_registry``'s declarations into a workspace's
``StaffRole`` rows.

Idempotent. Run on workspace creation, or via ``manage.py
sync_system_roles`` to backfill a deployment that added new module
roles since the workspace was first set up.

Important contract:

* Creating a row → copies ``default_permissions`` straight into
  ``permissions`` (the new role starts at the module-declared baseline).
* Updating a row → keeps the workspace's customised ``permissions``
  intact. Only ``name``, ``description``, ``default_permissions``,
  ``owner_module`` and ``is_system`` are refreshed from the registry.
* Restore-to-default is the only path that clobbers a role's
  ``permissions`` — implemented as a separate action on the API/UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List

from bfg.common.role_registry import RoleDefinition, role_registry

logger = logging.getLogger(__name__)


@dataclass
class ProvisionResult:
    created: List[str]
    updated: List[str]
    skipped: List[str]


def provision_system_roles(workspace, definitions: Iterable[RoleDefinition] | None = None) -> ProvisionResult:
    """Idempotently apply role definitions to the given workspace."""
    from bfg.common.models import StaffRole

    defs = list(definitions) if definitions is not None else role_registry.all_roles()
    created: List[str] = []
    updated: List[str] = []
    skipped: List[str] = []

    for d in defs:
        try:
            role, was_created = StaffRole.objects.get_or_create(
                workspace=workspace,
                code=d.code,
                defaults={
                    "name": d.name,
                    "description": d.description,
                    "permissions": d.cloned_defaults(),
                    "default_permissions": d.cloned_defaults(),
                    "owner_module": d.owner_module,
                    "is_system": True,
                    "is_active": True,
                },
            )
            if was_created:
                created.append(d.code)
                continue

            # Existing row — refresh metadata, but DO NOT clobber the
            # workspace admin's customised ``permissions`` JSON.
            dirty = False
            if role.name != d.name:
                role.name = d.name
                dirty = True
            if role.description != d.description:
                role.description = d.description
                dirty = True
            if role.default_permissions != d.default_permissions:
                role.default_permissions = d.cloned_defaults()
                dirty = True
            if role.owner_module != d.owner_module:
                role.owner_module = d.owner_module
                dirty = True
            if not role.is_system:
                role.is_system = True
                dirty = True
            if dirty:
                role.save(
                    update_fields=[
                        "name",
                        "description",
                        "default_permissions",
                        "owner_module",
                        "is_system",
                        "updated_at",
                    ]
                )
                updated.append(d.code)
            else:
                skipped.append(d.code)
        except Exception:
            logger.exception(
                "Failed to provision role %s for workspace %s", d.code, workspace.id
            )

    return ProvisionResult(created=created, updated=updated, skipped=skipped)


def restore_role_to_defaults(role) -> bool:
    """Reset ``permissions`` back to ``default_permissions``.

    Returns True if anything changed.
    """
    if not role.default_permissions:
        # No baseline known (legacy row that pre-dates the registry).
        return False
    if role.permissions == role.default_permissions:
        return False
    role.permissions = {
        k: list(v) if isinstance(v, list) else v
        for k, v in role.default_permissions.items()
    }
    role.save(update_fields=["permissions", "updated_at"])
    return True

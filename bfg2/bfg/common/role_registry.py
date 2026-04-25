# -*- coding: utf-8 -*-
"""
Workspace Role Registry

Each BFG module owns the roles that operate on its data (shop owns
``store_admin``, delivery owns ``warehouse_manager``, …) and registers
them at app startup via ``role_registry.register_role(...)``. The
common module then materialises the union of all registered roles into
a workspace's ``StaffRole`` table whenever a workspace is created or
``manage.py sync_system_roles`` runs.

Every system role keeps two permission JSON blobs:

* ``default_permissions`` — frozen at the module's declaration. Used to
  reset / restore.
* ``permissions`` — what the workspace actually enforces. Workspace
  admins can edit this freely; "Restore defaults" copies
  ``default_permissions`` back over it.

Modules also register a *permission catalog* — the human-readable list
of modules and actions they expose — so the role editor UI can render
a checkbox grid without hard-coding domain strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Data classes ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoleDefinition:
    """Declaration of a system role contributed by a module."""

    code: str
    name: str
    description: str
    default_permissions: Dict[str, List[str]]
    owner_module: str  # 'common', 'shop', 'delivery', …
    sort_order: int = 100  # lower numbers appear first in the UI

    def cloned_defaults(self) -> Dict[str, List[str]]:
        """Return a deep-ish copy of ``default_permissions`` safe to mutate."""
        return {k: list(v) if isinstance(v, list) else v for k, v in self.default_permissions.items()}


@dataclass(frozen=True)
class PermissionAction:
    """One action under a permission module (e.g. ``create`` under ``shop.product``)."""

    code: str
    label: str  # human-readable label, e.g. "Create"


@dataclass(frozen=True)
class PermissionModule:
    """A permission namespace exposed by a domain module.

    ``key`` is the dotted permission key checked at runtime
    (e.g. ``shop.product``). ``actions`` is the set of valid actions
    the role editor offers under that key.
    """

    key: str
    label: str  # e.g. "Products"
    owner_module: str  # 'shop', 'delivery', …
    group: str = ""  # optional grouping in UI ('Shop', 'Finance', …)
    actions: List[PermissionAction] = field(default_factory=list)
    sort_order: int = 100


# ── Registry ──────────────────────────────────────────────────────────


class _RoleRegistry:
    """Process-wide registry. Idempotent: re-registering the same code wins-last."""

    def __init__(self) -> None:
        self._roles: Dict[str, RoleDefinition] = {}
        self._modules: Dict[str, PermissionModule] = {}

    # — Roles —
    def register_role(self, definition: RoleDefinition) -> None:
        if not definition.code:
            raise ValueError("RoleDefinition.code is required")
        self._roles[definition.code] = definition

    def get_role(self, code: str) -> Optional[RoleDefinition]:
        return self._roles.get(code)

    def all_roles(self) -> List[RoleDefinition]:
        return sorted(
            self._roles.values(),
            key=lambda r: (r.sort_order, r.owner_module, r.code),
        )

    # — Permission catalog —
    def register_permission_module(self, module: PermissionModule) -> None:
        if not module.key:
            raise ValueError("PermissionModule.key is required")
        existing = self._modules.get(module.key)
        if existing:
            # Merge actions across multiple registrations of the same key.
            seen = {a.code for a in existing.actions}
            merged = list(existing.actions) + [a for a in module.actions if a.code not in seen]
            module = PermissionModule(
                key=module.key,
                label=module.label or existing.label,
                owner_module=module.owner_module or existing.owner_module,
                group=module.group or existing.group,
                actions=merged,
                sort_order=min(module.sort_order, existing.sort_order),
            )
        self._modules[module.key] = module

    def all_permission_modules(self) -> List[PermissionModule]:
        return sorted(
            self._modules.values(),
            key=lambda m: (m.sort_order, m.group, m.key),
        )

    def to_catalog_payload(self) -> List[dict]:
        """Serializable view of the full permission catalog (for the UI)."""
        return [
            {
                "key": m.key,
                "label": m.label,
                "owner_module": m.owner_module,
                "group": m.group,
                "sort_order": m.sort_order,
                "actions": [{"code": a.code, "label": a.label} for a in m.actions],
            }
            for m in self.all_permission_modules()
        ]


role_registry = _RoleRegistry()


# Convenience re-exports
__all__ = [
    "RoleDefinition",
    "PermissionAction",
    "PermissionModule",
    "role_registry",
]

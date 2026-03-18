# -*- coding: utf-8 -*-
"""
Agent capability contract and registry (bfg.core).

Each app defines capabilities in bfg.<app>.agent_capabilities (CAPABILITIES list)
and registers them in AppConfig.ready() via AgentCapabilityRegistry.register().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from rest_framework.permissions import BasePermission


@dataclass
class AgentCapability:
    """
    Single agent capability: id, name, description, app_label, input_schema, handler, required_permission.
    handler(request, **kwargs) -> dict; required_permission used to filter list and validate before execute.
    """
    id: str
    name: str
    description: str
    app_label: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Dict[str, Any]]
    required_permission: Tuple[Type[BasePermission], ...] = field(default_factory=tuple)

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialize for API (no handler)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "app_label": self.app_label,
            "input_schema": self.input_schema,
        }


class _FakeView:
    """Minimal view-like object for permission checks."""
    permission_classes: Tuple[Type[BasePermission], ...] = ()

    def __init__(self, permission_classes: Tuple[Type[BasePermission], ...]):
        self.permission_classes = permission_classes


class AgentCapabilityRegistry:
    """
    Global registry for agent capabilities. register(), get(), list_all(request=None).
    list_all(request) returns capabilities the user is allowed to execute.
    """
    _capabilities: Dict[str, AgentCapability] = {}

    @classmethod
    def register(cls, capability: AgentCapability) -> None:
        if capability.id in cls._capabilities:
            raise ValueError(f"Duplicate capability id: {capability.id}")
        cls._capabilities[capability.id] = capability

    @classmethod
    def get(cls, capability_id: str) -> Optional[AgentCapability]:
        return cls._capabilities.get(capability_id)

    @classmethod
    def list_all(
        cls,
        request: Optional[Any] = None,
    ) -> List[AgentCapability]:
        """
        Return all capabilities, or only those the user has permission to execute if request is provided.
        """
        all_caps = list(cls._capabilities.values())
        if request is None:
            return all_caps
        out = []
        view = _FakeView(())
        for cap in all_caps:
            if not cap.required_permission:
                out.append(cap)
                continue
            view.permission_classes = cap.required_permission
            allowed = all(
                perm().has_permission(request, view)
                for perm in cap.required_permission
            )
            if allowed:
                out.append(cap)
        return out


# Module-level singleton access
registry = AgentCapabilityRegistry()

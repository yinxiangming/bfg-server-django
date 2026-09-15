# -*- coding: utf-8 -*-
"""
Agent capability contract and registry (bfg.core).

Each app defines capabilities in bfg.<app>.agent_capabilities (CAPABILITIES list)
and registers them in AppConfig.ready() via AgentCapabilityRegistry.register().
A capability of an app whose extension the workspace does not use is neither listed
nor executed (see bfg.common.extensions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple, Type

from django.apps import apps
from rest_framework.permissions import BasePermission


@dataclass
class AgentCapability:
    """
    Single agent capability: id, name, description, app_label, input_schema, handler, required_permission.
    handler(request, **kwargs) -> dict; required_permission used to filter list and validate before execute.
    app_label is the label of the installed app the capability belongs to.
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


def _switched_off_apps(request: Any) -> FrozenSet[str]:
    """Labels of the apps whose extension the request's workspace does not use."""
    from bfg.common.extensions import unavailable_apps

    return unavailable_apps(getattr(request, "workspace", None))


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
        # A capability follows the extension of the app it names, so a label that is not an
        # installed app's would leave the capability ungated without a trace.
        try:
            apps.get_app_config(capability.app_label)
        except LookupError:
            raise ValueError(
                f"Capability {capability.id} names app_label {capability.app_label!r}, "
                f"which is not the label of an installed app"
            ) from None
        cls._capabilities[capability.id] = capability

    @classmethod
    def get(cls, capability_id: str) -> Optional[AgentCapability]:
        return cls._capabilities.get(capability_id)

    @classmethod
    def workspace_can_use(cls, request: Any, capability: AgentCapability) -> bool:
        """
        Whether the request's workspace can use the capability: always, unless its app
        ships an extension the workspace does not use.
        """
        return capability.app_label not in _switched_off_apps(request)

    @classmethod
    def list_all(
        cls,
        request: Optional[Any] = None,
    ) -> List[AgentCapability]:
        """
        Return all capabilities, or only those the user has permission to execute if request is provided.
        With a request, capabilities the workspace cannot use (see workspace_can_use) are left out too.
        """
        all_caps = list(cls._capabilities.values())
        if request is None:
            return all_caps
        switched_off = _switched_off_apps(request)
        out = []
        view = _FakeView(())
        for cap in all_caps:
            if cap.app_label in switched_off:
                continue
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

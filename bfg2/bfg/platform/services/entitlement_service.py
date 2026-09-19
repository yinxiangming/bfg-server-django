# -*- coding: utf-8 -*-
"""Runtime checks for Platform-granted features.

An entitlement is deliberately not a generic flag.  A key is only accepted
when a feature has a real server-side gate that consumes it.  This prevents an
operator from granting a value that looks active in the console but cannot
change customer access.
"""
from django.apps import apps
from django.db.models import Q
from django.utils import timezone


# Keep this registry small and evidence-based.  Each entry must have a runtime
# consumer and a focused test before it is exposed through the Platform console.
RUNTIME_ENTITLEMENT_KEYS = frozenset({"batch_management"})


def is_runtime_entitlement_key(key: str) -> bool:
    """Return whether ``key`` is consumed by an installed runtime gate."""
    return key in RUNTIME_ENTITLEMENT_KEYS


def has_active_entitlement(workspace, key: str, *, at=None) -> bool:
    """Return whether a currently effective Platform grant covers ``key``."""
    if not workspace or not getattr(workspace, "pk", None) or not is_runtime_entitlement_key(key):
        return False

    moment = at or timezone.now()
    Entitlement = apps.get_model("platform", "WorkspaceEntitlement")
    return Entitlement.objects.filter(
        workspace_id=workspace.pk,
        key=key,
        status=Entitlement.STATUS_ACTIVE,
        starts_at__lte=moment,
    ).filter(
        Q(current_period_end__isnull=True) | Q(current_period_end__gt=moment)
    ).exists()

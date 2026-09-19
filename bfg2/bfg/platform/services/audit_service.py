# -*- coding: utf-8 -*-
"""Small, shared audit boundary for Platform control-plane writes."""
import uuid

from django.apps import apps


_SENSITIVE_KEYS = frozenset({"redis_url", "platform_api_key", "agent_api_key", "password", "token"})


def _safe_value(value):
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if key.lower() in _SENSITIVE_KEYS else _safe_value(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return value


def _client_ip(request):
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


def _request_id(request):
    value = (request.headers.get("X-Request-ID") or "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def record_platform_audit(*, request, action, target_type, target_id, reason, before=None, after=None):
    """Record one completed control-plane action without retaining credentials."""
    PlatformAuditEvent = apps.get_model("platform", "PlatformAuditEvent")
    return PlatformAuditEvent.objects.create(
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        reason=reason,
        actor=request.user if getattr(request.user, "is_authenticated", False) else None,
        request_id=_request_id(request),
        source_ip=_client_ip(request),
        before=_safe_value(before or {}),
        after=_safe_value(after or {}),
    )

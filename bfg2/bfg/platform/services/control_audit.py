# -*- coding: utf-8 -*-
"""Audit-safe serialization for Platform control-plane evidence."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps


_SENSITIVE_KEYS = frozenset({
    "redis_url", "api_key", "platform_api_key", "agent_api_key", "database_url",
    "authorization", "cookie", "credentials",
})


def _is_sensitive_key(key) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return (
        normalized in _SENSITIVE_KEYS
        or "password" in normalized
        or "secret" in normalized
        or normalized.endswith("_token")
        or normalized.endswith("_api_key")
    )


def redact_control_value(value):
    """Return a JSON-safe nested snapshot without credentials."""
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if _is_sensitive_key(key) else redact_control_value(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_control_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _client_ip(request):
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


def _request_id(request):
    value = (request.headers.get("X-Request-ID") or "").strip()
    try:
        return uuid.UUID(value) if value else None
    except (TypeError, ValueError, AttributeError):
        return None


def record_control_audit(*, request, action, target_type, target_id, reason, before=None, after=None, result="succeeded"):
    """Store one append-only control-plane audit event with redacted snapshots."""
    PlatformAuditEvent = apps.get_model("platform", "PlatformAuditEvent")
    return PlatformAuditEvent.objects.create(
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        reason=reason,
        result=result,
        actor=request.user if getattr(request.user, "is_authenticated", False) else None,
        request_id=_request_id(request),
        source_ip=_client_ip(request),
        before=redact_control_value(before or {}),
        after=redact_control_value(after or {}),
    )

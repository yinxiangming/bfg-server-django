# -*- coding: utf-8 -*-
"""Small, shared audit boundary for Platform control-plane writes."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps


_SENSITIVE_KEYS = frozenset({
    "redis_url", "api_key", "platform_api_key", "agent_api_key", "database_url",
    "authorization", "cookie", "credentials",
})


def _is_sensitive_key(key):
    normalized = str(key).strip().lower().replace("-", "_")
    return (
        normalized in _SENSITIVE_KEYS
        or "password" in normalized
        or "secret" in normalized
        or normalized.endswith("_token")
        or normalized.endswith("_api_key")
    )


def redact_platform_audit_value(value):
    """Return an audit-safe copy of a nested request or state snapshot.

    This is used both before persistence and before API serialization.  The second
    pass protects the control plane if an older audit row predates redaction rules.
    """
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if _is_sensitive_key(key) else redact_platform_audit_value(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_platform_audit_value(item) for item in value]
    # Audit snapshots are JSONField values. Convert native ORM types here instead
    # of making every call site remember which values cannot be JSON encoded.
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
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def record_platform_audit(*, request, action, target_type, target_id, reason, before=None, after=None, result="succeeded"):
    """Record one completed control-plane action without retaining credentials."""
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
        before=redact_platform_audit_value(before or {}),
        after=redact_platform_audit_value(after or {}),
    )

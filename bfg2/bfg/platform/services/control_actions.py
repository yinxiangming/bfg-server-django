# -*- coding: utf-8 -*-
"""Confirmation, reason, and idempotency primitives for control-plane writes."""
import json
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from bfg.platform.models import PlatformControlActionRequest
from bfg.platform.services.control_audit import redact_control_value


def require_confirmation(request):
    """Require an explicit confirmation bit for an impactful write."""
    if not isinstance(request.data, dict) or request.data.get("confirm") is not True:
        raise ValidationError({"confirm": "Set confirm to true before making this change."})


def require_reason(request) -> str:
    """Return a durable, operator-supplied reason for a sensitive action."""
    value = request.data.get("reason") if isinstance(request.data, dict) else None
    value = value or request.headers.get("X-Platform-Change-Reason") or ""
    reason = str(value).strip()
    if len(reason) < 3:
        raise ValidationError({
            "code": "reason_required",
            "detail": "Provide a change reason of at least 3 characters.",
        })
    return reason[:500]


def _payload_hash(payload) -> str:
    body = json.dumps(redact_control_value(payload), sort_keys=True, separators=(",", ":"), default=str)
    return sha256(body.encode("utf-8")).hexdigest()


def _key(request) -> str:
    key = str(request.headers.get("X-Idempotency-Key") or "").strip()
    if not 8 <= len(key) <= 128:
        raise ValidationError({"idempotency_key": "Provide X-Idempotency-Key with 8 to 128 characters."})
    return key


def claim_action(request, *, action, target_type, target_id, payload):
    """Reserve a write or return the durable response from its prior attempt."""
    key = _key(request)
    payload_hash = _payload_hash(payload)
    try:
        with transaction.atomic():
            record, created = PlatformControlActionRequest.objects.get_or_create(
                created_by=request.user,
                idempotency_key=key,
                defaults={
                    "action": action,
                    "target_type": target_type,
                    "target_id": str(target_id),
                    "payload_hash": payload_hash,
                },
            )
    except IntegrityError:
        record = PlatformControlActionRequest.objects.get(
            created_by=request.user, idempotency_key=key,
        )
        created = False

    if created:
        return record, None
    if (
        record.action != action
        or record.target_type != target_type
        or record.target_id != str(target_id)
        or record.payload_hash != payload_hash
    ):
        return None, Response(
            {"detail": "This idempotency key was already used for a different Platform action.", "code": "idempotency_key_reused"},
            status=status.HTTP_409_CONFLICT,
        )
    if record.response_status is None:
        return None, Response(
            {"detail": "This action did not complete. Check the audit log before retrying with a new key.", "code": "idempotency_request_incomplete"},
            status=status.HTTP_409_CONFLICT,
        )
    response = Response(record.response_body, status=record.response_status)
    response["Idempotent-Replayed"] = "true"
    return None, response


def complete_action(record, *, result, response_status, response_body):
    """Persist a sanitized response before it is returned to a retrying client."""
    record.result = result
    record.response_status = response_status
    record.response_body = redact_control_value(response_body)
    record.completed_at = timezone.now()
    record.save(update_fields=["result", "response_status", "response_body", "completed_at"])

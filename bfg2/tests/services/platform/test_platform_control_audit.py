from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from bfg.platform.models import PlatformAuditEvent
from bfg.platform.services.control_audit import record_control_audit, redact_control_value


@pytest.mark.django_db
def test_record_control_audit_redacts_sensitive_values_and_persists_request_context():
    user = get_user_model().objects.create_superuser(
        username="platform-auditor",
        email="platform-auditor@example.test",
        password="not-a-production-password",
    )
    request = RequestFactory().post(
        "/api/v1/platform/control/workspaces/123/suspend/",
        HTTP_X_REQUEST_ID="5f6c56fa-c409-4b1e-b602-e32c73b4cf65",
        HTTP_X_FORWARDED_FOR="198.51.100.7, 10.0.0.1",
    )
    request.user = user

    event = record_control_audit(
        request=request,
        action="workspace.suspend",
        target_type="workspace",
        target_id=123,
        reason="Contract breach confirmed",
        before={"status": "active", "redis_url": "redis://credential"},
        after={
            "status": "suspended",
            "operator_password": "must-not-be-stored",
            "metadata": {"Authorization": "Bearer must-not-be-stored"},
        },
    )

    persisted = PlatformAuditEvent.objects.get(pk=event.pk)
    assert persisted.actor_id == user.id
    assert persisted.target_id == "123"
    assert persisted.source_ip == "198.51.100.7"
    assert persisted.request_id == UUID("5f6c56fa-c409-4b1e-b602-e32c73b4cf65")
    assert persisted.before == {"status": "active", "redis_url": "[redacted]"}
    assert persisted.after == {
        "status": "suspended",
        "operator_password": "[redacted]",
        "metadata": {"Authorization": "[redacted]"},
    }


def test_redact_control_value_is_recursive_and_json_safe():
    snapshot = redact_control_value(
        {
            "value": Decimal("39.00"),
            "effective_on": date(2026, 9, 20),
            "nested": [{"api-key": "secret"}, {"safe": "kept"}],
        }
    )

    assert snapshot == {
        "value": "39.00",
        "effective_on": "2026-09-20",
        "nested": [{"api-key": "[redacted]"}, {"safe": "kept"}],
    }

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from bfg.common.models import Workspace
from bfg.core.agent_views import AgentChatView
from bfg.platform.models import PlatformMeterPrice, WorkspaceMeterUsage, WorkspaceUsageCap
from bfg.platform.services.metering_service import (
    MeteringIdempotencyKeyRequired,
    WorkspaceUsageCapExceeded,
    record_meter_usage,
)


User = get_user_model()


@pytest.mark.django_db
def test_configured_meter_is_idempotent_and_enforces_the_workspace_cap():
    workspace = Workspace.objects.create(name="Metered Workspace", slug="metered-workspace", is_active=True)
    PlatformMeterPrice.objects.create(
        meter="ai.agent_chat", vendor_cost=Decimal("1"), unit_size=1, margin=Decimal("0"),
    )
    WorkspaceUsageCap.objects.create(workspace=workspace, cap_points=Decimal("1.0000"))

    first = record_meter_usage(workspace, "ai.agent_chat", 1, idempotency_key="chat-request-0001")
    repeated = record_meter_usage(workspace, "ai.agent_chat", 1, idempotency_key="chat-request-0001")

    assert first.metered is True
    assert first.points == Decimal("1.0000")
    assert repeated.record_id == first.record_id
    assert repeated.usage_after == Decimal("1.0000")
    assert WorkspaceMeterUsage.objects.count() == 1

    with pytest.raises(WorkspaceUsageCapExceeded):
        record_meter_usage(workspace, "ai.agent_chat", 1, idempotency_key="chat-request-0002")


@pytest.mark.django_db
def test_unpriced_meter_preserves_existing_behavior_without_an_idempotency_key():
    workspace = Workspace.objects.create(name="Unpriced Workspace", slug="unpriced-workspace", is_active=True)

    result = record_meter_usage(workspace, "ai.agent_chat", 1, idempotency_key=None)

    assert result.metered is False
    assert WorkspaceMeterUsage.objects.count() == 0


@pytest.mark.django_db
def test_priced_meter_requires_a_stable_idempotency_key():
    workspace = Workspace.objects.create(name="Keyed Workspace", slug="keyed-workspace", is_active=True)
    PlatformMeterPrice.objects.create(
        meter="ai.agent_chat", vendor_cost=Decimal("1"), unit_size=1, margin=Decimal("0"),
    )

    with pytest.raises(MeteringIdempotencyKeyRequired):
        record_meter_usage(workspace, "ai.agent_chat", 1, idempotency_key=None)


@pytest.mark.django_db
def test_agent_chat_rejects_a_capped_workspace_before_openai_is_called():
    user = User.objects.create_superuser(
        username="meter-agent-root", password="secret", email="meter-agent@example.test",
    )
    workspace = Workspace.objects.create(name="Capped Agent", slug="capped-agent", is_active=True)
    PlatformMeterPrice.objects.create(
        meter="ai.agent_chat", vendor_cost=Decimal("1"), unit_size=1, margin=Decimal("0"),
    )
    WorkspaceUsageCap.objects.create(workspace=workspace, cap_points=Decimal("0.0000"))
    request = APIRequestFactory().post(
        "/api/v1/agent/chat/",
        {"workspace_id": workspace.id, "messages": [{"role": "user", "content": "Hello"}]},
        format="json",
        HTTP_X_IDEMPOTENCY_KEY="agent-request-0001",
    )
    force_authenticate(request, user=user)

    response = AgentChatView.as_view()(request)

    assert response.status_code == 429
    assert response.data["code"] == "workspace_usage_cap_exceeded"
    assert WorkspaceMeterUsage.objects.count() == 0

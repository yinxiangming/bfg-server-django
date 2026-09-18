import pytest
from types import SimpleNamespace
from rest_framework.test import APIClient

from bfg.common.models import Workspace
from bfg.web.models import Inquiry
from bfg.web.services.inquiry_service import InquiryService


@pytest.mark.django_db
def test_create_inquiry_triggers_notification(monkeypatch):
    service = InquiryService(workspace=SimpleNamespace(id=1), user=None)
    captured = {}

    class _InquiryManager:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(id=12, **kwargs)

    monkeypatch.setattr("bfg.web.services.inquiry_service.Inquiry.objects", _InquiryManager())
    monkeypatch.setattr(service, "_send_notifications", lambda inquiry: captured.update({"id": inquiry.id}))

    inquiry = service.create_inquiry(name="A", message="B")
    assert inquiry.name == "A"
    assert captured["id"] == 12


@pytest.mark.django_db
def test_public_inquiry_endpoint_creates_an_inquiry():
    workspace = Workspace.objects.create(
        name="Public inquiry",
        slug="public-inquiry",
        is_active=True,
    )
    client = APIClient(HTTP_X_WORKSPACE_ID=str(workspace.id))

    response = client.post(
        "/api/v1/web/inquiries/",
        {
            "name": "Ada",
            "email": "ada@example.test",
            "message": "Please contact me",
        },
        format="json",
    )

    assert response.status_code == 201
    assert Inquiry.objects.filter(
        workspace=workspace,
        name="Ada",
        email="ada@example.test",
    ).exists()

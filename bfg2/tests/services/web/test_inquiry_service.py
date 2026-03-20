import pytest
from types import SimpleNamespace

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

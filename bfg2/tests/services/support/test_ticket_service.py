from datetime import datetime
from types import ModuleType, SimpleNamespace

import pytest

from tests.services._helpers import install_import_shims


@pytest.mark.django_db
def test_create_ticket_generates_number_and_initial_message(monkeypatch):
    install_import_shims()
    from bfg.support.services.ticket_service import TicketService

    service = TicketService(workspace=SimpleNamespace(id=1), user=None)
    customer = SimpleNamespace(user=SimpleNamespace(id=1))

    class _TicketManager:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(exists=lambda: False)

        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(**kwargs)

    captured = {}
    monkeypatch.setattr(
        "bfg.support.services.ticket_service.Ticket.objects",
        _TicketManager(),
    )
    monkeypatch.setattr(
        "bfg.support.services.ticket_service.TicketPriority.objects",
        SimpleNamespace(filter=lambda **_k: SimpleNamespace(first=lambda: None)),
    )
    monkeypatch.setattr(
        "bfg.support.services.ticket_service.TicketMessage.objects",
        SimpleNamespace(create=lambda **kwargs: captured.update(kwargs)),
    )
    monkeypatch.setattr("random.choices", lambda *_a, **_k: list("12345"))
    monkeypatch.setattr(
        "django.utils.timezone.now",
        lambda: datetime(2026, 3, 20, 12, 0, 0),
    )

    ticket = service.create_ticket(customer, "subject", "hello")
    assert ticket.ticket_number.startswith("TKT-20260320-")
    assert captured["sender_type"] == "customer"

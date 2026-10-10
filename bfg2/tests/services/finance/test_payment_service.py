from types import SimpleNamespace
from unittest.mock import patch

from bfg.finance.services.payment_service import PaymentService


def test_generate_payment_number_retries_until_unique(monkeypatch):
    service = PaymentService(workspace=None, user=None)
    seq = iter(["11111", "22222"])
    monkeypatch.setattr("random.choices", lambda *_a, **_k: list(next(seq)))

    class _Exists:
        def __init__(self):
            self.calls = 0

        def exists(self):
            self.calls += 1
            return self.calls == 1

    exists = _Exists()
    monkeypatch.setattr(
        "bfg.finance.services.payment_service.Payment.objects",
        SimpleNamespace(filter=lambda **_kwargs: exists),
    )
    number = service._generate_payment_number()
    assert number.startswith("PAY-")


def _consignment(pk):
    item = SimpleNamespace(pk=pk, status=None, state='PENDING')
    item.save = lambda **_kwargs: None
    return item


def _invoice_with(*consignments):
    queryset = SimpleNamespace(
        filter=lambda **_kwargs: list(consignments),
    )
    return SimpleNamespace(
        order=SimpleNamespace(
            consignments=queryset,
        ),
    )


def test_consignment_status_updates_workspace_candidates_without_receivers():
    workspace = SimpleNamespace(pk=7)
    service = PaymentService(workspace=workspace, user=None)
    ordinary = _consignment(11)
    status = SimpleNamespace(code='PAID')

    with patch('bfg.delivery.models.FreightStatus.objects.get', return_value=status):
        service._update_consignment_status(_invoice_with(ordinary), 'PAID')

    assert ordinary.status is status
    assert ordinary.state == 'PAID'


def test_consignment_status_uses_generic_exclusion_protocol():
    workspace = SimpleNamespace(pk=7)
    service = PaymentService(workspace=workspace, user=None)
    ordinary = _consignment(11)
    managed = _consignment(12)
    status = SimpleNamespace(code='PAID')

    with patch(
            'bfg.delivery.extension_signals.excluded_consignment_ids',
            return_value={12},
        ) as exclusions, \
            patch('bfg.delivery.models.FreightStatus.objects.get', return_value=status):
        service._update_consignment_status(
            _invoice_with(ordinary, managed),
            'PAID',
        )

    assert ordinary.status is status
    assert ordinary.state == 'PAID'
    assert managed.status is None
    assert managed.state == 'PENDING'
    exclusions.assert_called_once_with(
        workspace=workspace,
        candidate_ids=(11, 12),
        new_state='PAID',
    )

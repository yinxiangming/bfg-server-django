from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import OperationalError

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
    return SimpleNamespace(
        order=SimpleNamespace(
            consignments=SimpleNamespace(all=lambda: list(consignments)),
        ),
    )


def test_consignment_status_supports_legacy_wms_without_mobile_task():
    workspace = SimpleNamespace(pk=7)
    service = PaymentService(workspace=workspace, user=None)
    ordinary = _consignment(11)
    status = SimpleNamespace(code='PAID')

    with patch('django.apps.apps.is_installed', return_value=True), \
            patch('django.apps.apps.get_model', side_effect=LookupError('MobileTask')), \
            patch('bfg.delivery.models.FreightStatus.objects.get', return_value=status):
        service._update_consignment_status(_invoice_with(ordinary), 'PAID')

    assert ordinary.status is status
    assert ordinary.state == 'PAID'


def test_consignment_status_excludes_mobile_managed_delivery_tasks():
    workspace = SimpleNamespace(pk=7)
    service = PaymentService(workspace=workspace, user=None)
    ordinary = _consignment(11)
    mobile_managed = _consignment(12)
    status = SimpleNamespace(code='PAID')

    filter_calls = []
    task_query = SimpleNamespace(values_list=lambda *_args, **_kwargs: [12])
    mobile_tasks = SimpleNamespace(
        all_objects=SimpleNamespace(
            filter=lambda **kwargs: filter_calls.append(kwargs) or task_query,
        ),
    )
    with patch('django.apps.apps.is_installed', return_value=True), \
            patch('django.apps.apps.get_model', return_value=mobile_tasks), \
            patch('bfg.delivery.models.FreightStatus.objects.get', return_value=status):
        service._update_consignment_status(
            _invoice_with(ordinary, mobile_managed),
            'PAID',
        )

    assert ordinary.status is status
    assert ordinary.state == 'PAID'
    assert mobile_managed.status is None
    assert mobile_managed.state == 'PENDING'
    assert filter_calls == [{
        'workspace': workspace,
        'consignment_id__in': [11, 12],
        'kind': 'delivery',
    }]


def test_consignment_status_fails_closed_when_mobile_task_table_is_missing():
    workspace = SimpleNamespace(pk=7)
    service = PaymentService(workspace=workspace, user=None)
    ordinary = _consignment(11)

    def missing_table(**_kwargs):
        raise OperationalError('missing mobile task table')

    mobile_tasks = SimpleNamespace(
        all_objects=SimpleNamespace(filter=missing_table),
    )

    with patch('django.apps.apps.is_installed', return_value=True), \
            patch('django.apps.apps.get_model', return_value=mobile_tasks):
        with pytest.raises(OperationalError, match='missing mobile task table'):
            service._update_consignment_status(_invoice_with(ordinary), 'PAID')

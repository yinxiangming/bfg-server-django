"""The billing month as Celery tasks: thin wrappers, and nothing decided twice."""

import pytest

from bfg.platform import tasks

pytestmark = pytest.mark.django_db


def test_closing_periods_answers_what_the_sweep_settled(monkeypatch):
    monkeypatch.setattr(
        'bfg.platform.services.entitlements.close_due_periods',
        lambda: {'ended': 2},
    )

    assert tasks.close_entitlement_periods() == {'ended': 2}


def test_refreshing_rates_answers_how_many_were_written(monkeypatch):
    monkeypatch.setattr('bfg.platform.services.exchange_rates.refresh_rates', lambda: 7)

    assert tasks.refresh_exchange_rates() == 7


def test_issuing_bills_answers_ids_rather_than_invoices(monkeypatch):
    """A result backend has to be able to carry the answer."""

    class Invoice:
        def __init__(self, pk):
            self.pk = pk

    monkeypatch.setattr(
        'bfg.platform.services.billing.issue_monthly_bills',
        lambda month=None: [Invoice(3), Invoice(4)],
    )

    assert tasks.issue_monthly_bills() == [3, 4]


def test_the_month_asked_for_is_the_month_billed(monkeypatch):
    asked = []
    monkeypatch.setattr(
        'bfg.platform.services.billing.issue_monthly_bills',
        lambda month=None: asked.append(month) or [],
    )

    tasks.issue_monthly_bills('2026-08')

    assert asked == ['2026-08']

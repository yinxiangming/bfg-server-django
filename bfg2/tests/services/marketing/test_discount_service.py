from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.marketing.services.discount_service import DiscountCalculationService


@pytest.mark.django_db
def test_calculate_gift_card_amount_caps_by_remaining_total(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    gift_card = SimpleNamespace(balance=Decimal("30.00"), expires_at=None)
    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.GiftCard.objects",
        SimpleNamespace(get=lambda **_kwargs: gift_card),
    )

    amount = service._calculate_gift_card_amount("GC1", Decimal("50.00"), Decimal("25.00"))
    assert amount == Decimal("25.00")

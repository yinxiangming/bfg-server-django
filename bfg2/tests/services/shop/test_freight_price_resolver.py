from decimal import Decimal

import pytest

from bfg.shop.services import freight_price_resolver


@pytest.mark.django_db
def test_get_freight_price_value_resolves_product_and_direct_price(monkeypatch):
    class _PriceService:
        def get_effective_price(self, _product):
            return Decimal("19.90")

    class _ProductManager:
        @staticmethod
        def get(**_kwargs):
            return type("P", (), {"id": 12, "is_active": True})()

    monkeypatch.setattr(freight_price_resolver, "ProductPriceService", lambda: _PriceService())
    monkeypatch.setattr(freight_price_resolver.Product, "objects", _ProductManager())

    resolver = freight_price_resolver.get_freight_price_value(workspace=None)
    assert resolver({"product_id": 12}) == Decimal("19.90")
    assert resolver({"price": "7.8"}) == Decimal("7.8")

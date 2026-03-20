import pytest
from types import SimpleNamespace

from bfg.shop.exceptions import InsufficientStock
from bfg.shop.services.inventory_service import InventoryService


def test_allocate_stock_prefers_highest_quantity_first(monkeypatch):
    service = InventoryService(workspace=None, user=None)

    inv_a = SimpleNamespace(quantity=8, reserved=1, warehouse="W1")
    inv_b = SimpleNamespace(quantity=5, reserved=0, warehouse="W2")

    class _Available:
        def order_by(self, *_args):
            return self

        def aggregate(self, **_kwargs):
            return {"total": 12}

        def __iter__(self):
            return iter([inv_a, inv_b])

    monkeypatch.setattr(service, "get_available_warehouses", lambda *_args, **_kwargs: _Available())

    allocations = service.allocate_stock(variant=object(), required_quantity=9)
    assert allocations == [("W1", 7), ("W2", 2)]


def test_allocate_stock_raises_when_total_insufficient(monkeypatch):
    service = InventoryService(workspace=None, user=None)

    class _Available:
        def order_by(self, *_args):
            return self

        def aggregate(self, **_kwargs):
            return {"total": 1}

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(service, "get_available_warehouses", lambda *_args, **_kwargs: _Available())

    with pytest.raises(InsufficientStock, match="Only 1 units"):
        service.allocate_stock(variant=object(), required_quantity=2)

import pytest
from types import SimpleNamespace

from bfg.shop.exceptions import InsufficientStock
from bfg.shop.services.inventory_service import InventoryService


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# New tests
# ---------------------------------------------------------------------------

def test_allocate_stock_exactly_enough_in_one_warehouse(monkeypatch):
    service = InventoryService(workspace=None, user=None)

    inv = SimpleNamespace(quantity=5, reserved=0, warehouse="W1")

    class _Available:
        def order_by(self, *_args):
            return self

        def aggregate(self, **_kwargs):
            return {"total": 5}

        def __iter__(self):
            return iter([inv])

    monkeypatch.setattr(service, "get_available_warehouses", lambda *_args, **_kwargs: _Available())

    allocations = service.allocate_stock(variant=object(), required_quantity=5)
    assert allocations == [("W1", 5)]


def test_allocate_stock_split_across_multiple_warehouses(monkeypatch):
    service = InventoryService(workspace=None, user=None)

    inv_a = SimpleNamespace(quantity=3, reserved=0, warehouse="W1")
    inv_b = SimpleNamespace(quantity=4, reserved=0, warehouse="W2")

    class _Available:
        def order_by(self, *_args):
            return self

        def aggregate(self, **_kwargs):
            return {"total": 7}

        def __iter__(self):
            return iter([inv_a, inv_b])

    monkeypatch.setattr(service, "get_available_warehouses", lambda *_args, **_kwargs: _Available())

    allocations = service.allocate_stock(variant=object(), required_quantity=5)
    # Should take 3 from W1, then 2 from W2
    assert ("W1", 3) in allocations
    total_allocated = sum(qty for _, qty in allocations)
    assert total_allocated == 5


def test_allocate_stock_empty_warehouse_list_raises_insufficient(monkeypatch):
    service = InventoryService(workspace=None, user=None)

    class _Available:
        def order_by(self, *_args):
            return self

        def aggregate(self, **_kwargs):
            return {"total": 0}

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(service, "get_available_warehouses", lambda *_args, **_kwargs: _Available())

    with pytest.raises(InsufficientStock):
        service.allocate_stock(variant=object(), required_quantity=1)

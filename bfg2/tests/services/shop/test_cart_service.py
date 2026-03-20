from decimal import Decimal
from types import SimpleNamespace

from bfg.shop.services.cart_service import CartService


def test_calculate_cart_total_sums_item_subtotal():
    service = CartService(workspace=None, user=None)

    items = [SimpleNamespace(subtotal=Decimal("10.50")), SimpleNamespace(subtotal=Decimal("5.25"))]
    cart = SimpleNamespace(items=SimpleNamespace(select_related=lambda *_: items))

    assert service.calculate_cart_total(cart) == Decimal("15.75")


def test_get_cart_summary_includes_quantity_and_guest_flag(monkeypatch):
    service = CartService(workspace=None, user=None)
    items = [
        SimpleNamespace(quantity=2, subtotal=Decimal("4.00")),
        SimpleNamespace(quantity=1, subtotal=Decimal("6.00")),
    ]

    class _Items:
        def select_related(self, *_args):
            return self

        def all(self):
            return self

        def count(self):
            return len(items)

        def __iter__(self):
            return iter(items)

    cart = SimpleNamespace(id=7, customer=None, items=_Items())
    monkeypatch.setattr(service, "calculate_cart_total", lambda _cart: Decimal("10.00"))

    summary = service.get_cart_summary(cart)
    assert summary["cart_id"] == 7
    assert summary["total_quantity"] == 3
    assert summary["is_guest"] is True

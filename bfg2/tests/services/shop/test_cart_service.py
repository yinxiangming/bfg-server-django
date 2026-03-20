from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.shop.services.cart_service import CartService


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# get_or_create_cart
# ---------------------------------------------------------------------------

def test_get_or_create_cart_returns_existing(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    existing_cart = SimpleNamespace(id=42, customer="cust1")

    class _CartObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(order_by=lambda *_: SimpleNamespace(first=lambda: existing_cart))

    monkeypatch.setattr("bfg.shop.services.cart_service.Cart.objects", _CartObjects())

    cart = service.get_or_create_cart(customer="cust1")
    assert cart.id == 42


def test_get_or_create_cart_creates_when_none_exists(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    new_cart = SimpleNamespace(id=99, customer="cust2")

    class _CartObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(order_by=lambda *_: SimpleNamespace(first=lambda: None))

        @staticmethod
        def create(**kwargs):
            return new_cart

    monkeypatch.setattr("bfg.shop.services.cart_service.Cart.objects", _CartObjects())

    cart = service.get_or_create_cart(customer="cust2")
    assert cart.id == 99


# ---------------------------------------------------------------------------
# add_to_cart  (uses @transaction.atomic → needs django_db)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_add_to_cart_new_item_creates_cart_item(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product = SimpleNamespace(id=1, price=Decimal("10.00"), track_inventory=False)
    cart = SimpleNamespace(id=1)

    created_item = SimpleNamespace(quantity=1, price=Decimal("10.00"))

    class _CartItemObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: None)

        @staticmethod
        def create(**kwargs):
            return created_item

    monkeypatch.setattr("bfg.shop.services.cart_service.CartItem.objects", _CartItemObjects())

    item = service.add_to_cart(cart=cart, product=product, quantity=1, variant=None)
    assert item is created_item


@pytest.mark.django_db
def test_add_to_cart_existing_item_increments_quantity(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product = SimpleNamespace(id=1, price=Decimal("10.00"), track_inventory=False)
    cart = SimpleNamespace(id=1)

    saved = {}
    existing = SimpleNamespace(quantity=2, price=Decimal("10.00"), save=lambda: saved.update({"qty": existing.quantity}))

    class _CartItemObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: existing)

    monkeypatch.setattr("bfg.shop.services.cart_service.CartItem.objects", _CartItemObjects())

    item = service.add_to_cart(cart=cart, product=product, quantity=3, variant=None)
    assert item.quantity == 5
    assert saved["qty"] == 5


@pytest.mark.django_db
def test_add_to_cart_insufficient_stock_raises(monkeypatch):
    from bfg.shop.exceptions import InsufficientStock

    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product = SimpleNamespace(id=1, price=Decimal("10.00"), track_inventory=True, stock_quantity=2)
    cart = SimpleNamespace(id=1)

    with pytest.raises(InsufficientStock):
        service.add_to_cart(cart=cart, product=product, quantity=5, variant=None)


@pytest.mark.django_db
def test_add_to_cart_uses_variant_price_when_available(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product = SimpleNamespace(id=1, price=Decimal("10.00"), track_inventory=False)
    variant = SimpleNamespace(id=1, price=Decimal("15.00"), stock_quantity=10)
    cart = SimpleNamespace(id=1)

    created_kwargs = {}

    class _CartItemObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: None)

        @staticmethod
        def create(**kwargs):
            created_kwargs.update(kwargs)
            return SimpleNamespace(**kwargs)

    monkeypatch.setattr("bfg.shop.services.cart_service.CartItem.objects", _CartItemObjects())

    service.add_to_cart(cart=cart, product=product, quantity=1, variant=variant)
    assert created_kwargs["price"] == Decimal("15.00")


@pytest.mark.django_db
def test_add_to_cart_uses_product_price_when_variant_has_no_price(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product = SimpleNamespace(id=1, price=Decimal("10.00"), track_inventory=False)
    variant = SimpleNamespace(id=1, price=None, stock_quantity=10)
    cart = SimpleNamespace(id=1)

    created_kwargs = {}

    class _CartItemObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: None)

        @staticmethod
        def create(**kwargs):
            created_kwargs.update(kwargs)
            return SimpleNamespace(**kwargs)

    monkeypatch.setattr("bfg.shop.services.cart_service.CartItem.objects", _CartItemObjects())

    service.add_to_cart(cart=cart, product=product, quantity=1, variant=variant)
    assert created_kwargs["price"] == Decimal("10.00")


# ---------------------------------------------------------------------------
# update_cart_item_quantity  (uses @transaction.atomic)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_update_cart_item_quantity_updates_successfully():
    service = CartService(workspace=None, user=None)

    saved = {}
    cart_item = SimpleNamespace(
        quantity=1,
        product=SimpleNamespace(track_inventory=False),
        variant=None,
        save=lambda: saved.update({"qty": cart_item.quantity}),
    )

    result = service.update_cart_item_quantity(cart_item=cart_item, quantity=5)
    assert result.quantity == 5
    assert saved["qty"] == 5


@pytest.mark.django_db
def test_update_cart_item_quantity_exceeds_stock_raises():
    from bfg.shop.exceptions import InsufficientStock

    service = CartService(workspace=None, user=None)

    cart_item = SimpleNamespace(
        quantity=1,
        product=SimpleNamespace(track_inventory=True, stock_quantity=3),
        variant=None,
    )

    with pytest.raises(InsufficientStock):
        service.update_cart_item_quantity(cart_item=cart_item, quantity=10)


# ---------------------------------------------------------------------------
# clear_cart  (uses @transaction.atomic)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_clear_cart_deletes_all_items():
    service = CartService(workspace=None, user=None)

    deleted = {}
    items_manager = SimpleNamespace(
        all=lambda: SimpleNamespace(delete=lambda: deleted.update({"deleted": True}))
    )
    cart = SimpleNamespace(items=items_manager)

    service.clear_cart(cart)
    assert deleted.get("deleted") is True


# ---------------------------------------------------------------------------
# remove_from_cart  (no @transaction.atomic)
# ---------------------------------------------------------------------------

def test_remove_from_cart_deletes_specific_item():
    service = CartService(workspace=None, user=None)

    deleted = {}
    cart_item = SimpleNamespace(delete=lambda: deleted.update({"deleted": True}))

    service.remove_from_cart(cart_item)
    assert deleted.get("deleted") is True


# ---------------------------------------------------------------------------
# merge_guest_cart_to_customer  (uses @transaction.atomic)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_merge_guest_cart_no_guest_cart_returns_customer_cart(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    customer_cart = SimpleNamespace(id=10)

    class _CartObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: None)

    monkeypatch.setattr("bfg.shop.services.cart_service.Cart.objects", _CartObjects())
    monkeypatch.setattr(service, "get_or_create_cart", lambda customer: customer_cart)

    result = service.merge_guest_cart_to_customer("guest-session-key", "customer")
    assert result.id == 10


@pytest.mark.django_db
def test_merge_guest_cart_merges_quantities_for_same_product(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product = SimpleNamespace(id=1)

    saved = {}
    existing_item = SimpleNamespace(
        quantity=2,
        product=product,
        variant=None,
        save=lambda: saved.update({"qty": existing_item.quantity}),
    )

    guest_item = SimpleNamespace(quantity=3, product=product, variant=None)

    class _GuestCartItems:
        def all(self):
            return [guest_item]

    class _CustomerCartItems:
        def filter(self, **_kwargs):
            return SimpleNamespace(first=lambda: existing_item)

    customer_cart = SimpleNamespace(id=20, items=_CustomerCartItems())
    guest_cart = SimpleNamespace(
        id=1,
        items=_GuestCartItems(),
        delete=lambda: None,
    )

    class _CartObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: guest_cart)

    monkeypatch.setattr("bfg.shop.services.cart_service.Cart.objects", _CartObjects())
    monkeypatch.setattr(service, "get_or_create_cart", lambda customer: customer_cart)

    result = service.merge_guest_cart_to_customer("guest-session", "customer")

    assert result.id == 20
    assert existing_item.quantity == 5
    assert saved["qty"] == 5


@pytest.mark.django_db
def test_merge_guest_cart_moves_items_for_different_products(monkeypatch):
    service = CartService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    product_b = SimpleNamespace(id=2)

    saved = {}
    guest_item = SimpleNamespace(
        quantity=1,
        product=product_b,
        variant=None,
        cart=None,
        save=lambda: saved.update({"moved": True, "cart": guest_item.cart}),
    )

    class _CustomerCartItems:
        def filter(self, **_kwargs):
            return SimpleNamespace(first=lambda: None)

    customer_cart = SimpleNamespace(id=30, items=_CustomerCartItems())
    guest_cart = SimpleNamespace(
        id=2,
        items=SimpleNamespace(all=lambda: [guest_item]),
        delete=lambda: None,
    )

    class _CartObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: guest_cart)

    monkeypatch.setattr("bfg.shop.services.cart_service.Cart.objects", _CartObjects())
    monkeypatch.setattr(service, "get_or_create_cart", lambda customer: customer_cart)

    result = service.merge_guest_cart_to_customer("guest-session", "customer")

    assert result.id == 30
    assert saved.get("moved") is True
    assert saved.get("cart") is customer_cart

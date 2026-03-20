from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.shop.services.order_service import OrderService


# ---------------------------------------------------------------------------
# Existing test
# ---------------------------------------------------------------------------

def test_generate_order_number_retries_until_unique(monkeypatch):
    service = OrderService(workspace=None, user=None)

    seq = iter(["11111", "22222"])
    monkeypatch.setattr(
        "random.choices",
        lambda *_args, **_kwargs: list(next(seq)),
    )

    class _Exists:
        def __init__(self):
            self.calls = 0

        def exists(self):
            self.calls += 1
            return self.calls == 1

    exists = _Exists()
    monkeypatch.setattr(
        "bfg.shop.services.order_service.Order.objects",
        SimpleNamespace(filter=lambda **_kwargs: exists),
    )

    order_no = service._generate_order_number()
    assert order_no.startswith("ORD-")
    assert order_no.endswith("22222")


# ---------------------------------------------------------------------------
# _calculate_cart_weight
# ---------------------------------------------------------------------------

def test_calculate_cart_weight_uses_variant_weight_when_available():
    service = OrderService(workspace=None, user=None)

    item = SimpleNamespace(
        variant=SimpleNamespace(weight=Decimal("0.5")),
        product=SimpleNamespace(weight=Decimal("1.0")),
        quantity=2,
    )
    cart = SimpleNamespace(
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: [item])
        )
    )

    weight = service._calculate_cart_weight(cart)
    assert weight == Decimal("1.0")


def test_calculate_cart_weight_falls_back_to_product_weight():
    service = OrderService(workspace=None, user=None)

    item = SimpleNamespace(
        variant=SimpleNamespace(weight=None),
        product=SimpleNamespace(weight=Decimal("2.0")),
        quantity=3,
    )
    cart = SimpleNamespace(
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: [item])
        )
    )

    weight = service._calculate_cart_weight(cart)
    assert weight == Decimal("6.0")


def test_calculate_cart_weight_no_variant():
    service = OrderService(workspace=None, user=None)

    item = SimpleNamespace(
        variant=None,
        product=SimpleNamespace(weight=Decimal("1.5")),
        quantity=2,
    )
    cart = SimpleNamespace(
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: [item])
        )
    )

    weight = service._calculate_cart_weight(cart)
    assert weight == Decimal("3.0")


# ---------------------------------------------------------------------------
# _calculate_shipping_cost
# ---------------------------------------------------------------------------

def test_calculate_shipping_cost_freight_service_id_uses_base_plus_per_kg(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    freight = SimpleNamespace(
        config=None,
        base_price=Decimal("5.00"),
        price_per_kg=Decimal("2.00"),
    )
    monkeypatch.setattr(
        "bfg.shop.services.order_service.FreightService.objects",
        SimpleNamespace(get=lambda **_: freight),
    )

    cost = service._calculate_shipping_cost(freight_service_id=99, weight=Decimal("3.0"))
    assert cost == Decimal("11.00")


def _make_freight_service_mock_no_match():
    """Create a FreightService mock that raises DoesNotExist for get() and returns None for filter().first()."""

    class _FakeDoesNotExist(Exception):
        pass

    class _FakeFS:
        DoesNotExist = _FakeDoesNotExist
        objects = SimpleNamespace(
            get=lambda **_kw: (_ for _ in ()).throw(_FakeDoesNotExist()),
            filter=lambda **_kw: SimpleNamespace(first=lambda: None),
        )

    return _FakeFS


def test_calculate_shipping_cost_express_fallback(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    FakeFS = _make_freight_service_mock_no_match()
    monkeypatch.setattr("bfg.shop.services.order_service.FreightService", FakeFS)

    cost = service._calculate_shipping_cost(shipping_method="express")
    assert cost == Decimal("20.00")


def test_calculate_shipping_cost_standard_fallback(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    FakeFS = _make_freight_service_mock_no_match()
    monkeypatch.setattr("bfg.shop.services.order_service.FreightService", FakeFS)

    cost = service._calculate_shipping_cost(shipping_method="standard")
    assert cost == Decimal("10.00")


def test_calculate_shipping_cost_no_method_returns_default(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    FakeFS = _make_freight_service_mock_no_match()
    monkeypatch.setattr("bfg.shop.services.order_service.FreightService", FakeFS)

    cost = service._calculate_shipping_cost()
    assert cost == Decimal("10.00")


# ---------------------------------------------------------------------------
# _calculate_tax
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_calculate_tax_with_matching_state_rate(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    tax_rate = SimpleNamespace(rate=Decimal("10"))
    address = SimpleNamespace(country="NZ", state="AUK")

    class _TaxRateObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: tax_rate)

    monkeypatch.setattr(
        "bfg.finance.models.TaxRate.objects",
        _TaxRateObjects(),
    )

    tax = service._calculate_tax(Decimal("100.00"), address)
    assert tax == Decimal("10.00")


@pytest.mark.django_db
def test_calculate_tax_country_fallback(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    address = SimpleNamespace(country="NZ", state="AUK")
    tax_rate = SimpleNamespace(rate=Decimal("15"))

    call_count = {"n": 0}

    class _TaxRateObjects:
        @staticmethod
        def filter(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return SimpleNamespace(first=lambda: None)
            return SimpleNamespace(first=lambda: tax_rate)

    monkeypatch.setattr(
        "bfg.finance.models.TaxRate.objects",
        _TaxRateObjects(),
    )

    tax = service._calculate_tax(Decimal("200.00"), address)
    assert tax == Decimal("30.00")


@pytest.mark.django_db
def test_calculate_tax_no_rate_returns_zero(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    class _TaxRateObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(first=lambda: None)

    monkeypatch.setattr(
        "bfg.finance.models.TaxRate.objects",
        _TaxRateObjects(),
    )

    tax = service._calculate_tax(Decimal("100.00"), None)
    assert tax == Decimal("0.00")


# ---------------------------------------------------------------------------
# calculate_order_totals
# ---------------------------------------------------------------------------

def test_calculate_order_totals_empty_cart_returns_zeros():
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    cart = SimpleNamespace(
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: [])
        )
    )

    result = service.calculate_order_totals(cart)

    assert result["subtotal"] == Decimal("0.00")
    assert result["discount"] == Decimal("0.00")
    assert result["shipping_cost"] == Decimal("0.00")
    assert result["tax"] == Decimal("0.00")
    assert result["total"] == Decimal("0.00")
    assert result["shipping_discount"] == Decimal("0.00")


def _make_cart_items(*subtotals):
    """Return fake cart items with given subtotals."""
    items = []
    for st in subtotals:
        items.append(
            SimpleNamespace(
                subtotal=Decimal(str(st)),
                price=Decimal(str(st)),
                quantity=1,
                product=SimpleNamespace(id=1, name="P", track_inventory=False),
                variant=None,
            )
        )
    return items


def _patch_service_helpers(monkeypatch, service, discount_result=None, shipping=Decimal("10.00"), weight=Decimal("0"), tax=Decimal("0.00")):
    """Monkeypatch helpers on service instance."""
    if discount_result is None:
        discount_result = {
            "discount": Decimal("0.00"),
            "shipping_discount": Decimal("0.00"),
            "coupon_discount": Decimal("0.00"),
            "gift_card_amount": Decimal("0.00"),
        }
    monkeypatch.setattr(service, "_calculate_cart_weight", lambda _cart: weight)
    monkeypatch.setattr(service, "_calculate_shipping_cost", lambda **_kw: shipping)
    monkeypatch.setattr(service, "_calculate_tax", lambda *_a, **_kw: tax)

    class _FakeDiscountService:
        def __init__(self, *_a, **_kw):
            pass

        def calculate_order_discount(self, **_kw):
            return discount_result

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.DiscountCalculationService",
        _FakeDiscountService,
    )

    # Patch OrderItem so it doesn't validate FK constraints
    monkeypatch.setattr(
        "bfg.shop.services.order_service.OrderItem",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    # OrderItem() is constructed inside calculate_order_totals to build temp items.
    # Replace it with SimpleNamespace so Django FK checks don't fire.
    monkeypatch.setattr(
        "bfg.shop.services.order_service.OrderItem",
        lambda **kw: SimpleNamespace(**kw),
    )


def test_calculate_order_totals_normal_cart_no_coupon(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    items = _make_cart_items("30.00", "20.00")
    cart = SimpleNamespace(
        customer=None,
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: items)
        ),
    )
    _patch_service_helpers(monkeypatch, service, shipping=Decimal("10.00"), tax=Decimal("0.00"))

    result = service.calculate_order_totals(cart)

    assert result["subtotal"] == Decimal("50.00")
    assert result["discount"] == Decimal("0.00")
    assert result["shipping_cost"] == Decimal("10.00")
    assert result["total"] == Decimal("60.00")


def test_calculate_order_totals_with_coupon_applies_discount(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    items = _make_cart_items("100.00")
    cart = SimpleNamespace(
        customer=None,
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: items)
        ),
    )
    discount_result = {
        "discount": Decimal("10.00"),
        "shipping_discount": Decimal("0.00"),
        "coupon_discount": Decimal("10.00"),
        "gift_card_amount": Decimal("0.00"),
    }
    _patch_service_helpers(monkeypatch, service, discount_result=discount_result, shipping=Decimal("10.00"))

    result = service.calculate_order_totals(cart, coupon_code="SAVE10")

    assert result["coupon_discount"] == Decimal("10.00")
    assert result["discount"] == Decimal("10.00")
    assert result["total"] == Decimal("100.00")


def test_calculate_order_totals_with_gift_card(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    items = _make_cart_items("80.00")
    cart = SimpleNamespace(
        customer=None,
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: items)
        ),
    )
    discount_result = {
        "discount": Decimal("0.00"),
        "shipping_discount": Decimal("0.00"),
        "coupon_discount": Decimal("0.00"),
        "gift_card_amount": Decimal("20.00"),
    }
    _patch_service_helpers(monkeypatch, service, discount_result=discount_result, shipping=Decimal("0.00"))

    result = service.calculate_order_totals(cart, gift_card_code="GC123")

    assert result["discount"] == Decimal("20.00")
    assert result["total"] == Decimal("60.00")


def test_calculate_order_totals_coupon_and_gift_card_combined(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    items = _make_cart_items("100.00")
    cart = SimpleNamespace(
        customer=None,
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: items)
        ),
    )
    discount_result = {
        "discount": Decimal("10.00"),
        "shipping_discount": Decimal("0.00"),
        "coupon_discount": Decimal("10.00"),
        "gift_card_amount": Decimal("15.00"),
    }
    _patch_service_helpers(monkeypatch, service, discount_result=discount_result, shipping=Decimal("10.00"))

    result = service.calculate_order_totals(cart, coupon_code="SAVE10", gift_card_code="GC1")

    # discount = base discount(10) + gift_card(15) = 25
    assert result["discount"] == Decimal("25.00")
    assert result["total"] == Decimal("85.00")  # 100 + 10 shipping - 25 discount


def test_calculate_order_totals_free_shipping_discount_sets_shipping_to_zero(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)

    items = _make_cart_items("50.00")
    cart = SimpleNamespace(
        customer=None,
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: items)
        ),
    )
    discount_result = {
        "discount": Decimal("0.00"),
        "shipping_discount": Decimal("999999.99"),
        "coupon_discount": Decimal("0.00"),
        "gift_card_amount": Decimal("0.00"),
    }
    _patch_service_helpers(monkeypatch, service, discount_result=discount_result, shipping=Decimal("10.00"))

    result = service.calculate_order_totals(cart, coupon_code="FREESHIP")

    assert result["shipping_cost"] == Decimal("0.00")
    assert result["total"] == Decimal("50.00")


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cancel_order_normal(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    saved = {}
    events = {}

    order = SimpleNamespace(
        order_number="ORD-001",
        status="pending",
        admin_note="",
        save=lambda: saved.update({"status": order.status}),
    )
    monkeypatch.setattr(service, "emit_event", lambda name, data: events.update({"name": name}))

    class _FakeAudit:
        def __init__(self, **_kw):
            pass

        def log_update(self, *_a, **_kw):
            pass

    monkeypatch.setattr("bfg.shop.services.order_service.AuditService", _FakeAudit)

    result = service.cancel_order(order, reason="Customer request")

    assert result.status == "cancelled"
    assert saved["status"] == "cancelled"
    assert events["name"] == "order.cancelled"


@pytest.mark.django_db
def test_cancel_order_delivered_raises_exception(monkeypatch):
    from bfg.shop.exceptions import OrderNotCancellable

    service = OrderService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    order = SimpleNamespace(order_number="ORD-002", status="delivered", admin_note="")

    with pytest.raises(OrderNotCancellable):
        service.cancel_order(order)


@pytest.mark.django_db
def test_cancel_order_already_cancelled_raises_exception(monkeypatch):
    from bfg.shop.exceptions import OrderNotCancellable

    service = OrderService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    order = SimpleNamespace(order_number="ORD-003", status="cancelled", admin_note="")

    with pytest.raises(OrderNotCancellable):
        service.cancel_order(order)


# ---------------------------------------------------------------------------
# update_order_status
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_update_order_status_shipped_sets_shipped_at(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    events = {}

    order = SimpleNamespace(
        order_number="ORD-010",
        status="processing",
        shipped_at=None,
        delivered_at=None,
        save=lambda: None,
    )
    monkeypatch.setattr(service, "emit_event", lambda name, data: events.update({"name": name}))

    class _FakeAudit:
        def __init__(self, **_kw):
            pass

        def log_update(self, *_a, **_kw):
            pass

    monkeypatch.setattr("bfg.shop.services.order_service.AuditService", _FakeAudit)

    # Patch Order.STATUS_CHOICES to avoid AttributeError on dict()
    monkeypatch.setattr(
        "bfg.shop.services.order_service.Order.STATUS_CHOICES",
        [("shipped", "Shipped"), ("delivered", "Delivered")],
        raising=False,
    )

    result = service.update_order_status(order, "shipped")

    assert result.status == "shipped"
    assert result.shipped_at is not None
    assert events["name"] == "order.shipped"


@pytest.mark.django_db
def test_update_order_status_delivered_sets_delivered_at(monkeypatch):
    service = OrderService(workspace=SimpleNamespace(id=1), user=None)
    monkeypatch.setattr(service, "validate_workspace_access", lambda _obj: None)

    events = {}

    order = SimpleNamespace(
        order_number="ORD-011",
        status="shipped",
        shipped_at=None,
        delivered_at=None,
        save=lambda: None,
    )
    monkeypatch.setattr(service, "emit_event", lambda name, data: events.update({"name": name}))

    class _FakeAudit:
        def __init__(self, **_kw):
            pass

        def log_update(self, *_a, **_kw):
            pass

    monkeypatch.setattr("bfg.shop.services.order_service.AuditService", _FakeAudit)
    monkeypatch.setattr(
        "bfg.shop.services.order_service.Order.STATUS_CHOICES",
        [("shipped", "Shipped"), ("delivered", "Delivered")],
        raising=False,
    )

    result = service.update_order_status(order, "delivered")

    assert result.status == "delivered"
    assert result.delivered_at is not None
    assert events["name"] == "order.delivered"

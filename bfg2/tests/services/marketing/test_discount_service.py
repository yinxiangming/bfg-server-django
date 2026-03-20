from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.marketing.services.discount_service import DiscountCalculationService


# ---------------------------------------------------------------------------
# Existing test
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _make_order_item(product_id=1, subtotal="50.00", variant_product_id=None, category_ids=None):
    product = SimpleNamespace(
        id=product_id,
        categories=SimpleNamespace(
            values_list=lambda *_a, **_kw: category_ids or []
        ),
    )
    variant = None
    if variant_product_id is not None:
        variant = SimpleNamespace(product=SimpleNamespace(id=variant_product_id))
    return SimpleNamespace(
        product=product,
        variant=variant,
        subtotal=Decimal(subtotal),
    )


def _make_discount_rule(
    discount_type="percentage",
    discount_value="10",
    apply_to="order",
    minimum_purchase=None,
    maximum_discount=None,
    product_ids=None,
    category_ids=None,
):
    products_qs = SimpleNamespace(values_list=lambda *_a, **_kw: list(product_ids or []))
    categories_qs = SimpleNamespace(values_list=lambda *_a, **_kw: list(category_ids or []))
    return SimpleNamespace(
        discount_type=discount_type,
        discount_value=Decimal(discount_value),
        apply_to=apply_to,
        minimum_purchase=Decimal(str(minimum_purchase)) if minimum_purchase is not None else None,
        maximum_discount=Decimal(str(maximum_discount)) if maximum_discount is not None else None,
        products=products_qs,
        categories=categories_qs,
    )


def _now_minus(days=0):
    from django.utils import timezone
    from datetime import timedelta
    return timezone.now() - timedelta(days=days)


def _now_plus(days=1):
    from django.utils import timezone
    from datetime import timedelta
    return timezone.now() + timedelta(days=days)


# ---------------------------------------------------------------------------
# calculate_order_discount — top-level
# ---------------------------------------------------------------------------

def test_calculate_order_discount_no_coupon_no_gift_card_returns_zeros(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    monkeypatch.setattr(service, "_calculate_auto_discount", lambda **_kw: {"discount": Decimal("0.00"), "shipping_discount": Decimal("0.00")})

    result = service.calculate_order_discount(
        order_items=[],
        subtotal=Decimal("100.00"),
    )

    assert result["discount"] == Decimal("0.00")
    assert result["shipping_discount"] == Decimal("0.00")
    assert result["coupon_discount"] == Decimal("0.00")
    assert result["gift_card_amount"] == Decimal("0.00")


def test_calculate_order_discount_with_coupon(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    monkeypatch.setattr(
        service,
        "_calculate_coupon_discount",
        lambda **_kw: {"discount": Decimal("15.00"), "shipping_discount": Decimal("0.00")},
    )

    result = service.calculate_order_discount(
        order_items=[],
        subtotal=Decimal("100.00"),
        coupon_code="SAVE15",
    )

    assert result["coupon_discount"] == Decimal("15.00")
    assert result["discount"] == Decimal("15.00")


def test_calculate_order_discount_with_gift_card(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    monkeypatch.setattr(service, "_calculate_auto_discount", lambda **_kw: {"discount": Decimal("0.00"), "shipping_discount": Decimal("0.00")})
    monkeypatch.setattr(service, "_calculate_gift_card_amount", lambda *_a, **_kw: Decimal("20.00"))

    result = service.calculate_order_discount(
        order_items=[],
        subtotal=Decimal("100.00"),
        gift_card_code="GC99",
    )

    assert result["gift_card_amount"] == Decimal("20.00")
    # discount is only coupon_discount (gift card tracked separately)
    assert result["discount"] == Decimal("0.00")


def test_calculate_order_discount_coupon_and_gift_card_combined(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    monkeypatch.setattr(
        service,
        "_calculate_coupon_discount",
        lambda **_kw: {"discount": Decimal("10.00"), "shipping_discount": Decimal("0.00")},
    )
    monkeypatch.setattr(service, "_calculate_gift_card_amount", lambda *_a, **_kw: Decimal("25.00"))

    result = service.calculate_order_discount(
        order_items=[],
        subtotal=Decimal("100.00"),
        coupon_code="TENOFF",
        gift_card_code="GC50",
    )

    assert result["coupon_discount"] == Decimal("10.00")
    assert result["gift_card_amount"] == Decimal("25.00")


# ---------------------------------------------------------------------------
# _calculate_coupon_discount
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_calculate_coupon_discount_percentage_on_order(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(discount_type="percentage", discount_value="10", apply_to="order")
    coupon = SimpleNamespace(
        discount_rule=rule,
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    result = service._calculate_coupon_discount(
        coupon_code="PERC10",
        order_items=[_make_order_item()],
        subtotal=Decimal("100.00"),
    )
    assert result["discount"] == Decimal("10.00")


@pytest.mark.django_db
def test_calculate_coupon_discount_fixed_amount_on_order(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(discount_type="fixed_amount", discount_value="20", apply_to="order")
    coupon = SimpleNamespace(
        discount_rule=rule,
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    result = service._calculate_coupon_discount(
        coupon_code="FIX20",
        order_items=[_make_order_item(subtotal="50.00")],
        subtotal=Decimal("50.00"),
    )
    assert result["discount"] == Decimal("20.00")


@pytest.mark.django_db
def test_calculate_coupon_discount_free_shipping_type(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(discount_type="free_shipping", discount_value="0", apply_to="order")
    coupon = SimpleNamespace(
        discount_rule=rule,
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    result = service._calculate_coupon_discount(
        coupon_code="FREESHIP",
        order_items=[_make_order_item(subtotal="80.00")],
        subtotal=Decimal("80.00"),
    )
    assert result["discount"] == Decimal("0.00")
    assert result["shipping_discount"] > Decimal("0.00")


@pytest.mark.django_db
def test_calculate_coupon_discount_expired_coupon_returns_zero(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(discount_type="percentage", discount_value="10", apply_to="order")
    coupon = SimpleNamespace(
        discount_rule=rule,
        valid_from=_now_minus(10),
        valid_until=_now_minus(1),  # expired
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    result = service._calculate_coupon_discount(
        coupon_code="EXPIRED",
        order_items=[_make_order_item()],
        subtotal=Decimal("100.00"),
    )
    assert result["discount"] == Decimal("0.00")


@pytest.mark.django_db
def test_calculate_coupon_discount_usage_limit_reached_returns_zero(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(discount_type="percentage", discount_value="10", apply_to="order")
    coupon = SimpleNamespace(
        discount_rule=rule,
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=5,
        times_used=5,  # limit reached
        usage_limit_per_customer=None,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    result = service._calculate_coupon_discount(
        coupon_code="MAXED",
        order_items=[_make_order_item()],
        subtotal=Decimal("100.00"),
    )
    assert result["discount"] == Decimal("0.00")


@pytest.mark.django_db
def test_calculate_coupon_discount_minimum_purchase_not_met_returns_zero(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(
        discount_type="percentage",
        discount_value="10",
        apply_to="order",
        minimum_purchase="200",
    )
    coupon = SimpleNamespace(
        discount_rule=rule,
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    result = service._calculate_coupon_discount(
        coupon_code="MINPURCH",
        order_items=[_make_order_item(subtotal="50.00")],
        subtotal=Decimal("50.00"),  # below minimum
    )
    assert result["discount"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# _calculate_product_discount
# ---------------------------------------------------------------------------

def test_calculate_product_discount_percentage_matching_products():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(
        discount_type="percentage",
        discount_value="20",
        apply_to="products",
        product_ids=[1],
    )
    items = [_make_order_item(product_id=1, subtotal="100.00")]

    discount = service._calculate_product_discount(rule, items, "percentage")
    assert discount == Decimal("20.00")


def test_calculate_product_discount_fixed_amount_matching_products():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(
        discount_type="fixed_amount",
        discount_value="15",
        apply_to="products",
        product_ids=[1],
    )
    items = [_make_order_item(product_id=1, subtotal="100.00")]

    discount = service._calculate_product_discount(rule, items, "fixed_amount")
    assert discount == Decimal("15.00")


def test_calculate_product_discount_no_matching_products_returns_zero():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(
        discount_type="percentage",
        discount_value="20",
        apply_to="products",
        product_ids=[99],  # product 99 not in cart
    )
    items = [_make_order_item(product_id=1, subtotal="100.00")]

    discount = service._calculate_product_discount(rule, items, "percentage")
    assert discount == Decimal("0.00")


# ---------------------------------------------------------------------------
# _calculate_category_discount
# ---------------------------------------------------------------------------

def test_calculate_category_discount_percentage_matching_categories():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(
        discount_type="percentage",
        discount_value="10",
        apply_to="categories",
        category_ids=[5],
    )
    items = [_make_order_item(product_id=1, subtotal="100.00", category_ids=[5, 6])]

    discount = service._calculate_category_discount(rule, items, "percentage")
    assert discount == Decimal("10.00")


def test_calculate_category_discount_no_matching_categories_returns_zero():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(
        discount_type="percentage",
        discount_value="10",
        apply_to="categories",
        category_ids=[99],
    )
    items = [_make_order_item(product_id=1, subtotal="100.00", category_ids=[5])]

    discount = service._calculate_category_discount(rule, items, "percentage")
    assert discount == Decimal("0.00")


# ---------------------------------------------------------------------------
# _validate_coupon
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_validate_coupon_valid_returns_none(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(minimum_purchase=None)
    coupon = SimpleNamespace(
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
        discount_rule=rule,
    )

    error = service._validate_coupon(coupon, Decimal("100.00"), customer=None)
    assert error is None


@pytest.mark.django_db
def test_validate_coupon_not_yet_valid_returns_error():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(minimum_purchase=None)
    coupon = SimpleNamespace(
        valid_from=_now_plus(2),  # future
        valid_until=_now_plus(10),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
        discount_rule=rule,
    )

    error = service._validate_coupon(coupon, Decimal("100.00"), customer=None)
    assert error is not None
    assert "not yet valid" in error.lower()


@pytest.mark.django_db
def test_validate_coupon_expired_returns_error():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(minimum_purchase=None)
    coupon = SimpleNamespace(
        valid_from=_now_minus(10),
        valid_until=_now_minus(1),  # expired
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
        discount_rule=rule,
    )

    error = service._validate_coupon(coupon, Decimal("100.00"), customer=None)
    assert error is not None
    assert "expired" in error.lower()


@pytest.mark.django_db
def test_validate_coupon_usage_limit_reached_returns_error():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(minimum_purchase=None)
    coupon = SimpleNamespace(
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=3,
        times_used=3,  # exhausted
        usage_limit_per_customer=None,
        discount_rule=rule,
    )

    error = service._validate_coupon(coupon, Decimal("100.00"), customer=None)
    assert error is not None
    assert "limit" in error.lower()


@pytest.mark.django_db
def test_validate_coupon_minimum_purchase_not_met_returns_error():
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(minimum_purchase="200")
    coupon = SimpleNamespace(
        valid_from=_now_minus(1),
        valid_until=_now_plus(1),
        usage_limit=None,
        times_used=0,
        usage_limit_per_customer=None,
        discount_rule=rule,
    )

    error = service._validate_coupon(coupon, Decimal("50.00"), customer=None)
    assert error is not None
    assert "minimum" in error.lower() or "purchase" in error.lower()


# ---------------------------------------------------------------------------
# _calculate_gift_card_amount (additional cases beyond existing test)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_calculate_gift_card_amount_normal_balance_greater_than_remaining(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    gift_card = SimpleNamespace(balance=Decimal("100.00"), expires_at=None)
    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.GiftCard.objects",
        SimpleNamespace(get=lambda **_kw: gift_card),
    )

    # remaining = 80 - 10 = 70; balance 100 > 70 → cap at 70
    amount = service._calculate_gift_card_amount("GC1", Decimal("80.00"), Decimal("10.00"))
    assert amount == Decimal("70.00")


@pytest.mark.django_db
def test_calculate_gift_card_amount_balance_less_than_remaining(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    gift_card = SimpleNamespace(balance=Decimal("5.00"), expires_at=None)
    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.GiftCard.objects",
        SimpleNamespace(get=lambda **_kw: gift_card),
    )

    # remaining = 100 - 0 = 100; balance 5 < 100 → use balance 5
    amount = service._calculate_gift_card_amount("GC2", Decimal("100.00"), Decimal("0.00"))
    assert amount == Decimal("5.00")


@pytest.mark.django_db
def test_calculate_gift_card_amount_expired_gift_card_returns_zero(monkeypatch):
    from django.utils import timezone
    from datetime import timedelta

    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    gift_card = SimpleNamespace(
        balance=Decimal("50.00"),
        expires_at=timezone.now() - timedelta(days=1),  # expired
    )
    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.GiftCard.objects",
        SimpleNamespace(get=lambda **_kw: gift_card),
    )

    amount = service._calculate_gift_card_amount("GCEXP", Decimal("80.00"), Decimal("0.00"))
    assert amount == Decimal("0.00")


@pytest.mark.django_db
def test_calculate_gift_card_amount_invalid_code_returns_zero(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    class _GiftCardObjects:
        @staticmethod
        def get(**_kwargs):
            from bfg.marketing.models import GiftCard
            raise GiftCard.DoesNotExist()

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.GiftCard.objects",
        _GiftCardObjects(),
    )

    amount = service._calculate_gift_card_amount("INVALID", Decimal("80.00"), Decimal("0.00"))
    assert amount == Decimal("0.00")


# ---------------------------------------------------------------------------
# _calculate_auto_discount
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_calculate_auto_discount_matches_best_percentage_rule(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule_low = _make_discount_rule(discount_type="percentage", discount_value="5", apply_to="order", minimum_purchase=None)
    rule_high = _make_discount_rule(discount_type="percentage", discount_value="20", apply_to="order", minimum_purchase=None)

    class _RuleObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(order_by=lambda *_: [rule_low, rule_high])

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.DiscountRule.objects",
        _RuleObjects(),
    )

    result = service._calculate_auto_discount(
        order_items=[_make_order_item(subtotal="100.00")],
        subtotal=Decimal("100.00"),
    )
    # Best discount: 20% of 100 = 20
    assert result["discount"] == Decimal("20.00")


@pytest.mark.django_db
def test_calculate_auto_discount_free_shipping_rule_applied(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_discount_rule(discount_type="free_shipping", discount_value="0", apply_to="order", minimum_purchase=None)

    class _RuleObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(order_by=lambda *_: [rule])

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.DiscountRule.objects",
        _RuleObjects(),
    )

    result = service._calculate_auto_discount(
        order_items=[_make_order_item(subtotal="50.00")],
        subtotal=Decimal("50.00"),
    )
    assert result["shipping_discount"] > Decimal("0.00")


@pytest.mark.django_db
def test_calculate_auto_discount_minimum_purchase_filter(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    # Rule requires min purchase 200 but subtotal is 50
    rule = _make_discount_rule(discount_type="percentage", discount_value="20", apply_to="order", minimum_purchase="200")

    class _RuleObjects:
        @staticmethod
        def filter(**_kwargs):
            return SimpleNamespace(order_by=lambda *_: [rule])

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.DiscountRule.objects",
        _RuleObjects(),
    )

    result = service._calculate_auto_discount(
        order_items=[_make_order_item(subtotal="50.00")],
        subtotal=Decimal("50.00"),
    )
    # Minimum not met → no discount
    assert result["discount"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# apply_coupon_to_order
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_apply_coupon_to_order_updates_discount_and_total(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    monkeypatch.setattr(
        service,
        "_calculate_coupon_discount",
        lambda **_kw: {"discount": Decimal("15.00"), "shipping_discount": Decimal("0.00")},
    )

    saved = {}
    order = SimpleNamespace(
        subtotal=Decimal("100.00"),
        shipping_cost=Decimal("10.00"),
        tax=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("110.00"),
        items=SimpleNamespace(
            select_related=lambda *_: SimpleNamespace(all=lambda: [])
        ),
        save=lambda: saved.update({"discount": order.discount, "total": order.total}),
    )

    class _CouponObjects:
        @staticmethod
        def get(**_kwargs):
            c = SimpleNamespace(times_used=0, save=lambda: None)
            return c

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.Coupon.objects",
        _CouponObjects(),
    )

    discount, err = service.apply_coupon_to_order(order, "SAVE15")

    assert discount == Decimal("15.00")
    assert err is None
    assert saved["discount"] == Decimal("15.00")
    assert saved["total"] == Decimal("95.00")


# ---------------------------------------------------------------------------
# apply_gift_card_to_order
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_apply_gift_card_to_order_deducts_from_gift_card_balance(monkeypatch):
    service = DiscountCalculationService(workspace=SimpleNamespace(id=1), user=None)

    monkeypatch.setattr(
        service,
        "_calculate_gift_card_amount",
        lambda *_a, **_kw: Decimal("30.00"),
    )

    gift_card_data = {"balance": Decimal("50.00")}

    class _GiftCardObjects:
        @staticmethod
        def get(**_kwargs):
            return SimpleNamespace(
                balance=gift_card_data["balance"],
                save=lambda: gift_card_data.update({"balance": gc.balance}),
            )

    gc = _GiftCardObjects.get()
    real_gc = gc

    def _get_gc(**_kw):
        return real_gc

    monkeypatch.setattr(
        "bfg.marketing.services.discount_service.GiftCard.objects",
        SimpleNamespace(get=_get_gc),
    )

    saved = {}
    order = SimpleNamespace(
        subtotal=Decimal("100.00"),
        shipping_cost=Decimal("10.00"),
        tax=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("110.00"),
        save=lambda: saved.update({"discount": order.discount, "total": order.total}),
    )

    amount, err = service.apply_gift_card_to_order(order, "GC50")

    assert amount == Decimal("30.00")
    assert err is None
    assert saved["discount"] == Decimal("30.00")

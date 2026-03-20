from decimal import Decimal

from bfg.marketing.services.promo_service import CouponService


def test_calculate_discount_applies_maximum_cap():
    service = CouponService(workspace=None, user=None)
    rule = type(
        "Rule",
        (),
        {"discount_type": "percentage", "discount_value": Decimal("20"), "maximum_discount": Decimal("15")},
    )()

    discount = service._calculate_discount(rule, Decimal("100"))
    assert discount == Decimal("15")

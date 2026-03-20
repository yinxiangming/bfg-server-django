from decimal import Decimal

from bfg.delivery.services.freight_calculator import calculate_base_shipping_cost, calculate_billing_weight


def test_calculate_billing_weight_uses_max_actual_or_volumetric():
    billing_weight = calculate_billing_weight(
        actual_weight=Decimal("1.00"),
        length=Decimal("20"),
        width=Decimal("20"),
        height=Decimal("20"),
        volumetric_factor=5000,
    )
    assert billing_weight == Decimal("1.60")


def test_calculate_base_shipping_cost_step_mode():
    config = {
        "mode": "step",
        "rules": {
            "first_weight": 1,
            "first_price": 10,
            "additional_weight": 1,
            "additional_price": 3,
        },
    }
    assert calculate_base_shipping_cost(Decimal("2.2"), config) == Decimal("16")

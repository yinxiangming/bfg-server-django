"""
Unit tests for FreightService config as documented in docs/freight_service_config.md.
Verifies bfg.delivery.services.freight_calculator (no apps.wms dependency).
"""

import pytest
from decimal import Decimal

from bfg.delivery.services.freight_calculator import (
    calculate_billing_weight,
    calculate_base_shipping_cost,
    find_matching_rule,
    normalize_conditions,
)


class TestCalculateBillingWeight:
    """Test billing weight = max(actual, volumetric)."""

    def test_actual_only_when_no_dims(self):
        assert calculate_billing_weight(Decimal('5')) == Decimal('5')

    def test_volumetric_when_greater(self):
        w = calculate_billing_weight(
            Decimal('5'),
            length=Decimal('50'),
            width=Decimal('40'),
            height=Decimal('30'),
            volumetric_factor=5000,
        )
        assert w == Decimal('12.00')

    def test_actual_when_greater_than_volumetric(self):
        w = calculate_billing_weight(
            Decimal('20'),
            length=Decimal('10'),
            width=Decimal('10'),
            height=Decimal('10'),
            volumetric_factor=5000,
        )
        assert w == Decimal('20')


class TestCalculateBaseShippingCostLinear:
    """Doc section 3.1: mode linear - flat_rate, base_plus_per_kg."""

    def test_flat_rate_fixed_price(self):
        config = {'mode': 'linear', 'rules': {'fixed_price': 15}, 'currency': 'NZD'}
        assert calculate_base_shipping_cost(Decimal('3'), config) == Decimal('15')
        assert calculate_base_shipping_cost(Decimal('100'), config) == Decimal('15')

    def test_base_plus_per_kg(self):
        config = {'mode': 'linear', 'rules': {'base': 10, 'per_kg': 2}, 'currency': 'NZD'}
        assert calculate_base_shipping_cost(Decimal('0'), config) == Decimal('10')
        assert calculate_base_shipping_cost(Decimal('3'), config) == Decimal('16')
        assert calculate_base_shipping_cost(Decimal('5'), config) == Decimal('20')


class TestCalculateBaseShippingCostStep:
    """Doc section 3.2: mode step - first_kg_then_per_kg."""

    def test_first_weight_included(self):
        config = {
            'mode': 'step',
            'rules': {'first_weight': 5, 'first_price': 20, 'additional_weight': 1, 'additional_price': 1},
            'currency': 'NZD',
        }
        assert calculate_base_shipping_cost(Decimal('3'), config) == Decimal('20')
        assert calculate_base_shipping_cost(Decimal('5'), config) == Decimal('20')

    def test_over_first_weight_rounds_up_additional(self):
        config = {
            'mode': 'step',
            'rules': {'first_weight': 5, 'first_price': 20, 'additional_weight': 1, 'additional_price': 1},
            'currency': 'NZD',
        }
        assert calculate_base_shipping_cost(Decimal('6'), config) == Decimal('21')
        assert calculate_base_shipping_cost(Decimal('6.5'), config) == Decimal('22')


class TestCalculateBaseShippingCostTier:
    """Doc section 3.3: mode tier - rules.tiers with max_kg and price."""

    def test_weight_tiers_doc_format(self):
        config = {
            'mode': 'tier',
            'rules': {
                'tiers': [
                    {'max_kg': 5, 'price': 10},
                    {'max_kg': 10, 'price': 18},
                    {'max_kg': 20, 'price': 25},
                ]
            },
            'currency': 'NZD',
        }
        assert calculate_base_shipping_cost(Decimal('3'), config) == Decimal('10')
        assert calculate_base_shipping_cost(Decimal('5'), config) == Decimal('10')
        assert calculate_base_shipping_cost(Decimal('6'), config) == Decimal('18')
        assert calculate_base_shipping_cost(Decimal('10'), config) == Decimal('18')
        assert calculate_base_shipping_cost(Decimal('15'), config) == Decimal('25')
        assert calculate_base_shipping_cost(Decimal('25'), config) == Decimal('25')


class TestConditionNormalizeAndMatch:
    """Template conditions (type/value) normalize to engine format and match context."""

    def test_normalize_weight_gte(self):
        out = normalize_conditions([{'type': 'weight_gte', 'value': 10}])
        assert out == {'operator': 'AND', 'rules': [{'field': 'freight.weight', 'operator': '>=', 'value': 10}]}

    def test_normalize_order_amount_gte(self):
        out = normalize_conditions([{'type': 'order_amount_gte', 'value': 100}])
        assert out == {'operator': 'AND', 'rules': [{'field': 'freight.order_amount', 'operator': '>=', 'value': 100}]}

    def test_find_matching_rule_weight_gte(self):
        config = {
            'mode': 'conditional',
            'pricing_rules': [
                {'priority': 1, 'conditions': [{'type': 'weight_gte', 'value': 10}], 'pricing': {'type': 'free'}},
                {'priority': 2, 'conditions': [], 'pricing': {'type': 'linear', 'base': 5, 'per_kg': 2}},
            ],
        }
        context_heavy = {'freight': {'weight': Decimal('15')}, 'weight': Decimal('15')}
        context_light = {'freight': {'weight': Decimal('5')}, 'weight': Decimal('5')}
        rule_heavy = find_matching_rule(config, context_heavy)
        rule_light = find_matching_rule(config, context_light)
        assert rule_heavy is not None and rule_heavy.get('pricing', {}).get('type') == 'free'
        assert rule_light is not None
        assert rule_light.get('pricing', {}).get('type') in ('free', 'linear')

    def test_conditional_free_then_linear_via_direct_cost_call(self):
        rule_config_free = {'mode': 'linear', 'rules': {'fixed_price': 0}}
        rule_config_linear = {'mode': 'linear', 'rules': {'base': 5, 'per_kg': 2}}
        assert calculate_base_shipping_cost(Decimal('10'), rule_config_free) == Decimal('0')
        assert calculate_base_shipping_cost(Decimal('10'), rule_config_linear) == Decimal('25')



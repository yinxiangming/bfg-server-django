"""
ConditionEngine rule evaluation.

Every one of these fails against the pre-fix engine, which returned True for any leaf
rule. `_evaluate_rule` dispatched nested-vs-leaf on the presence of an 'operator' key —
but a leaf carries one too ({'field': ..., 'operator': '>=', 'value': ...}), so leaves
recursed into `evaluate`, found no 'rules' list, and hit the "empty rules always match"
branch. `_compare` was unreachable.

Freight pricing is the only consumer, and there the effect was expensive rather than
cosmetic: a conditional service always resolved to its first rule by priority, so a
service built from the `free_over_amount` template shipped free at every order value.
"""

from decimal import Decimal

import pytest

from bfg.core.condition_engine import ConditionEngine


@pytest.fixture
def engine():
    return ConditionEngine()


def group(*rules, operator='AND'):
    return {'operator': operator, 'rules': list(rules)}


GTE_100 = {'field': 'freight.order_amount', 'operator': '>=', 'value': 100}


# ------------------------------------------------------------ leaf rules


@pytest.mark.parametrize('amount,expected', [(50, False), (99.99, False), (100, True), (150, True)])
def test_a_threshold_rule_compares_instead_of_always_matching(engine, amount, expected):
    context = {'freight': {'order_amount': amount}}
    assert engine.evaluate(group(GTE_100), context) is expected


def test_a_decimal_actual_compares_against_an_int_threshold(engine):
    """Money arrives as Decimal; the threshold is written as a plain number in JSON."""
    assert engine.evaluate(group(GTE_100), {'freight': {'order_amount': Decimal('100.00')}}) is True
    assert engine.evaluate(group(GTE_100), {'freight': {'order_amount': Decimal('99.99')}}) is False


def test_a_field_missing_from_the_context_does_not_match(engine):
    assert engine.evaluate(group(GTE_100), {}) is False
    assert engine.evaluate(group(GTE_100), {'freight': {}}) is False
    assert engine.evaluate(group(GTE_100), {'freight': {'order_amount': None}}) is False


def test_a_top_level_field_resolves_without_a_prefix(engine):
    rule = {'field': 'weight', 'operator': '<', 'value': 3}
    assert engine.evaluate(group(rule), {'weight': Decimal('0.4')}) is True
    assert engine.evaluate(group(rule), {'weight': Decimal('5')}) is False


@pytest.mark.parametrize('operator,value,actual,expected', [
    ('==', 'NZ', 'NZ', True),
    ('!=', 'NZ', 'AU', True),
    ('>', 10, 10, False),
    ('<=', 10, 10, True),
    ('in', ['NZ', 'AU'], 'NZ', True),
    ('in', ['NZ', 'AU'], 'US', False),
    ('not_in', ['NZ', 'AU'], 'US', True),
    ('contains', 'NZ', ['NZ', 'AU'], True),
])
def test_each_operator_actually_compares(engine, operator, value, actual, expected):
    rule = {'field': 'country', 'operator': operator, 'value': value}
    assert engine.evaluate(group(rule), {'country': actual}) is expected


def test_an_unknown_operator_is_an_error_rather_than_a_match(engine):
    rule = {'field': 'weight', 'operator': 'roughly', 'value': 1}
    with pytest.raises(ValueError):
        engine.evaluate(group(rule), {'weight': 1})


# ------------------------------------------------------ groups and nesting


def test_and_requires_every_rule(engine):
    rules = group(GTE_100, {'field': 'weight', 'operator': '<', 'value': 3})
    assert engine.evaluate(rules, {'freight': {'order_amount': 120}, 'weight': 1}) is True
    assert engine.evaluate(rules, {'freight': {'order_amount': 120}, 'weight': 9}) is False


def test_or_requires_only_one(engine):
    rules = group(GTE_100, {'field': 'weight', 'operator': '<', 'value': 3}, operator='OR')
    assert engine.evaluate(rules, {'freight': {'order_amount': 10}, 'weight': 1}) is True
    assert engine.evaluate(rules, {'freight': {'order_amount': 10}, 'weight': 9}) is False


def test_a_nested_group_is_still_recursed_into(engine):
    """The branch that leaves were wrongly taking still has to work for real groups."""
    nested = group(
        {'field': 'country', 'operator': '==', 'value': 'NZ'},
        group(GTE_100, {'field': 'weight', 'operator': '>=', 'value': 3}, operator='OR'),
    )
    assert engine.evaluate(nested, {'country': 'NZ', 'freight': {'order_amount': 120}, 'weight': 1}) is True
    assert engine.evaluate(nested, {'country': 'NZ', 'freight': {'order_amount': 10}, 'weight': 5}) is True
    assert engine.evaluate(nested, {'country': 'NZ', 'freight': {'order_amount': 10}, 'weight': 1}) is False
    assert engine.evaluate(nested, {'country': 'AU', 'freight': {'order_amount': 120}, 'weight': 1}) is False


def test_no_condition_at_all_matches(engine):
    """A rule with nothing to check is the catch-all every pricing table needs last."""
    assert engine.evaluate(None, {}) is True
    assert engine.evaluate(group(), {}) is True


def test_a_rule_without_a_field_is_an_error(engine):
    with pytest.raises(ValueError):
        engine.evaluate(group({'operator': '>=', 'value': 100}), {})

# -*- coding: utf-8 -*-
"""
Freight config-based calculator (billing weight, base shipping cost, conditional rule resolution).
Belongs to bfg.delivery; no dependency on apps.wms.
"""

from decimal import Decimal
import math
from typing import Any, Callable, Dict, Optional

from bfg.core.condition_engine import get_condition_engine


def calculate_billing_weight(
    actual_weight: Decimal,
    length: Optional[Decimal] = None,
    width: Optional[Decimal] = None,
    height: Optional[Decimal] = None,
    volumetric_factor: Optional[int] = None,
) -> Decimal:
    """
    Billing weight = max(actual, volumetric).
    Volumetric = (L*W*H) / factor when dimensions and factor are provided.
    """
    if not volumetric_factor or not all([length, width, height]):
        return actual_weight
    volumetric_weight = (
        Decimal(str(length)) * Decimal(str(width)) * Decimal(str(height))
    ) / Decimal(str(volumetric_factor))
    return max(actual_weight, volumetric_weight.quantize(Decimal("0.01")))


def normalize_conditions(conditions: Any) -> Optional[Dict[str, Any]]:
    """
    Convert template-style conditions (list of {type, value}) to engine format
    (operator + rules with field, operator, value).
    """
    if conditions is None:
        return None
    if isinstance(conditions, dict) and "rules" in conditions:
        return conditions
    if not isinstance(conditions, list) or not conditions:
        return None
    rules_out = []
    for c in conditions:
        if not isinstance(c, dict):
            continue
        cond_type = c.get("type")
        val = c.get("value")
        if cond_type == "weight_gte":
            rules_out.append({"field": "freight.weight", "operator": ">=", "value": val})
        elif cond_type == "order_amount_gte":
            rules_out.append(
                {"field": "freight.order_amount", "operator": ">=", "value": val}
            )
        elif "field" in c and "operator" in c:
            rules_out.append(c)
    if not rules_out:
        return None
    return {"operator": "AND", "rules": rules_out}


def find_matching_rule(
    config: Dict[str, Any], context: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Find first matching pricing rule by priority. Supports template (type/value)
    and engine (field/operator/value) condition formats.
    """
    pricing_rules = config.get("pricing_rules", [])
    if not pricing_rules:
        return None
    sorted_rules = sorted(pricing_rules, key=lambda r: r.get("priority", 999))
    engine = get_condition_engine()
    for rule in sorted_rules:
        raw_conditions = rule.get("conditions")
        conditions = normalize_conditions(raw_conditions)
        if conditions is None:
            if not raw_conditions:
                return rule
            continue
        if engine.evaluate(conditions, context):
            return rule
    return None


def resolve_conditional_config(
    config: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    If config mode is 'conditional', resolve to effective linear/step/tier config
    using the first matching rule. Otherwise return config unchanged.
    """
    mode = config.get("mode", "linear")
    if mode != "conditional":
        return config
    matched = find_matching_rule(config, context)
    if not matched:
        raise ValueError("No matching pricing rule found for conditional config")
    rule_pricing = matched.get("pricing", {})
    ptype = rule_pricing.get("type")
    if ptype == "free":
        rules_for_mode = {"fixed_price": 0}
    elif (
        ptype == "linear"
        and rule_pricing.get("base") is not None
        and rule_pricing.get("per_kg") is not None
    ):
        rules_for_mode = {
            "base": rule_pricing["base"],
            "per_kg": rule_pricing["per_kg"],
        }
    else:
        rules_for_mode = {
            "first_unit": rule_pricing.get("first_unit", {}),
            "additional_unit": rule_pricing.get("additional_unit", {}),
        }
    return {
        **config,
        "mode": "linear",
        "rules": rules_for_mode,
        "min_charge": matched.get("min_charge"),
        "surcharges": matched.get("surcharges", config.get("surcharges", [])),
        "discounts": matched.get("discounts", []),
    }


def _default_get_price_value(price_config: Any) -> Decimal:
    """Resolve price from dict (price or product_id) or scalar. No product lookup."""
    if isinstance(price_config, dict):
        if price_config.get("product_id"):
            raise ValueError(
                "product_id in price config requires get_price_value callback"
            )
        return Decimal(str(price_config.get("price", 0)))
    return Decimal(str(price_config))


def calculate_base_shipping_cost(
    weight: Decimal,
    config: Dict[str, Any],
    get_price_value: Optional[Callable[[Any], Decimal]] = None,
) -> Decimal:
    """
    Base shipping cost from weight and config (mode: linear, step, tier).
    get_price_value: optional callable(price_config) for resolving product_id or
    dict with price; used for step/tier when rules reference products.
    """
    mode = config.get("mode", "linear")
    rules = config.get("rules", {})
    get_price = get_price_value or _default_get_price_value

    if mode == "step":
        first_weight = Decimal(str(rules.get("first_weight", 0)))
        first_price = get_price(rules.get("first_price", 0))
        additional_weight = Decimal(str(rules.get("additional_weight", 1)))
        additional_price = get_price(rules.get("additional_price", 0))
        if weight <= first_weight:
            return first_price
        extra_weight = weight - first_weight
        increments = Decimal(str(math.ceil(float(extra_weight / additional_weight))))
        return first_price + (increments * additional_price)

    if mode == "linear":
        if rules.get("fixed_price") is not None:
            return Decimal(str(rules["fixed_price"]))
        base = rules.get("base")
        per_kg = rules.get("per_kg")
        if base is not None and per_kg is not None:
            return Decimal(str(base)) + (weight * Decimal(str(per_kg)))
        first_unit = rules.get("first_unit", {})
        additional_unit = rules.get("additional_unit", {})
        if first_unit or additional_unit:
            first_price = get_price(first_unit)
            additional_price = get_price(additional_unit)
            if weight <= 1:
                return first_price
            return first_price + ((weight - 1) * additional_price)
        unit_price = Decimal(str(rules.get("unit_price", 0)))
        min_charge = Decimal(str(rules.get("min_charge", 0)))
        cost = weight * unit_price
        return max(cost, min_charge)

    if mode == "tier":
        tiers_list = rules.get("tiers") if isinstance(rules, dict) else None
        if isinstance(tiers_list, list) and tiers_list:
            sorted_tiers = sorted(
                tiers_list, key=lambda t: Decimal(str(t.get("max_kg", 0)))
            )
            for tier in sorted_tiers:
                max_kg = Decimal(str(tier.get("max_kg", 0)))
                if weight <= max_kg:
                    return get_price(tier.get("price", 0))
            return get_price(sorted_tiers[-1].get("price", 0))
        match_type = config.get("match_type", "unit_price")
        tier_rules = rules if isinstance(rules, list) else []
        for tier in tier_rules:
            t_min = Decimal(str(tier.get("min", 0)))
            t_max = Decimal(str(tier.get("max", 999999)))
            if t_min <= weight < t_max:
                price = get_price(tier.get("price", 0))
                if match_type == "fixed_price":
                    return price
                return weight * price
        return Decimal("0.00")

    return Decimal("0.00")


def calculate_shipping_cost(
    weight: Decimal,
    config: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    get_price_value: Optional[Callable[[Any], Decimal]] = None,
) -> Decimal:
    """
    Single entry: resolve conditional if needed, then compute base cost.
    context is used only when mode is 'conditional'.
    """
    effective = (
        resolve_conditional_config(config, context)
        if (config.get("mode") == "conditional" and context)
        else config
    )
    return calculate_base_shipping_cost(weight, effective, get_price_value)

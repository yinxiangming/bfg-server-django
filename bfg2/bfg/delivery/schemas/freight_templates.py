"""
Freight pricing templates: load JSON templates from disk and convert form params to config.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Directory for freight pricing template JSON files (avoids confusion with Django templates)
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "freight_pricing_templates"

_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _load_templates() -> Dict[str, Dict[str, Any]]:
    """Scan templates dir for *.json and return dict id -> template."""
    global _cache
    if _cache is not None:
        return _cache
    result: Dict[str, Dict[str, Any]] = {}
    if not _TEMPLATES_DIR.is_dir():
        _cache = result
        return result
    for path in _TEMPLATES_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tid = data.get("id")
            if tid:
                result[tid] = data
        except (json.JSONDecodeError, OSError):
            continue
    _cache = result
    return result


def get_all_templates() -> List[Dict[str, Any]]:
    """Return list of template definitions (id, label, label_zh, description, description_zh, mode, form_schema)."""
    templates = _load_templates()
    return list(templates.values())


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    """Return one template by id."""
    return _load_templates().get(template_id)


def form_params_to_config(
    template_id: str, form_data: Dict[str, Any]
) -> Tuple[Dict[str, Any], Any, Any]:
    """
    Build FreightService.config and (base_price, price_per_kg) from template id and form params.
    Returns (config_dict, base_price_decimal, price_per_kg_decimal).
    """
    template = get_template(template_id)
    if not template:
        raise ValueError(f"Unknown template: {template_id}")

    mode = template.get("mode", "linear")
    currency = form_data.get("currency") or None
    if currency == "":
        currency = None

    def dec(v: Any) -> Any:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return v

    config: Dict[str, Any] = {
        "mode": mode,
        "currency": currency,
        "unit": "kg",
        "rules": {},
        "pricing_rules": [],
        "surcharges": [],
        "discounts": [],
    }
    base_price: Any = 0
    price_per_kg: Any = 0

    if template_id == "flat_rate":
        amount = dec(form_data.get("amount"))
        if amount is None:
            raise ValueError("amount is required for flat_rate")
        config["rules"] = {"fixed_price": amount}
        base_price = amount
        price_per_kg = 0

    elif template_id == "base_plus_per_kg":
        base = dec(form_data.get("base"))
        per_kg = dec(form_data.get("per_kg"))
        if base is None:
            raise ValueError("base is required for base_plus_per_kg")
        if per_kg is None:
            raise ValueError("per_kg is required for base_plus_per_kg")
        config["rules"] = {"base": base, "per_kg": per_kg}
        base_price = base
        price_per_kg = per_kg

    elif template_id == "first_kg_then_per_kg":
        fw = dec(form_data.get("first_weight"))
        fp = dec(form_data.get("first_price"))
        aw = dec(form_data.get("additional_weight"))
        ap = dec(form_data.get("additional_price"))
        if fw is None or fp is None or aw is None or ap is None:
            raise ValueError("first_weight, first_price, additional_weight, additional_price required")
        config["rules"] = {
            "first_weight": fw,
            "first_price": fp,
            "additional_weight": aw,
            "additional_price": ap,
        }
        base_price = fp
        price_per_kg = 0  # step pricing is not linear

    elif template_id == "weight_tiers":
        tiers = form_data.get("tiers")
        if isinstance(tiers, str):
            try:
                tiers = json.loads(tiers)
            except json.JSONDecodeError as e:
                raise ValueError(f"tiers: invalid JSON ({e})") from e
        if not isinstance(tiers, list) or not tiers:
            raise ValueError("tiers must be a non-empty array")
        out_tiers = []
        for i, row in enumerate(tiers):
            if isinstance(row, dict):
                mk = dec(row.get("max_kg"))
                pr = dec(row.get("price"))
            else:
                mk = pr = None
            if mk is None or pr is None:
                raise ValueError(f"tiers[{i}]: max_kg and price required")
            out_tiers.append({"max_kg": mk, "price": pr})
        out_tiers.sort(key=lambda x: x["max_kg"])
        config["rules"] = {"tiers": out_tiers}
        base_price = out_tiers[0]["price"] if out_tiers else 0
        price_per_kg = 0

    elif template_id == "free_over_amount":
        threshold = dec(form_data.get("threshold_amount"))
        fb = dec(form_data.get("fallback_base"))
        fk = dec(form_data.get("fallback_per_kg"))
        if threshold is None:
            raise ValueError("threshold_amount is required")
        if fb is None:
            raise ValueError("fallback_base is required")
        if fk is None:
            raise ValueError("fallback_per_kg is required")
        config["mode"] = "conditional"
        config["pricing_rules"] = [
            {
                "priority": 1,
                "conditions": [{"type": "order_amount_gte", "value": threshold}],
                "pricing": {"type": "free"},
            },
            {
                "priority": 2,
                "conditions": [],
                "pricing": {"type": "linear", "base": fb, "per_kg": fk},
            },
        ]
        config["rules"] = {}
        base_price = fb
        price_per_kg = fk

    elif template_id == "free_over_weight":
        threshold = dec(form_data.get("threshold_kg"))
        fb = dec(form_data.get("fallback_base"))
        fk = dec(form_data.get("fallback_per_kg"))
        if threshold is None:
            raise ValueError("threshold_kg is required")
        if fb is None:
            raise ValueError("fallback_base is required")
        if fk is None:
            raise ValueError("fallback_per_kg is required")
        config["mode"] = "conditional"
        config["pricing_rules"] = [
            {
                "priority": 1,
                "conditions": [{"type": "weight_gte", "value": threshold}],
                "pricing": {"type": "free"},
            },
            {
                "priority": 2,
                "conditions": [],
                "pricing": {"type": "linear", "base": fb, "per_kg": fk},
            },
        ]
        config["rules"] = {}
        base_price = fb
        price_per_kg = fk

    elif template_id == "first_cbm_then_per_cbm":
        first_cbm = dec(form_data.get("first_cbm"))
        first_cbm_price = dec(form_data.get("first_cbm_price"))
        additional_cbm_price = dec(form_data.get("additional_cbm_price"))
        max_weight_kg = dec(form_data.get("max_weight_kg"))
        vol_factor = dec(form_data.get("volumetric_factor"))
        if first_cbm is None or first_cbm_price is None or additional_cbm_price is None:
            raise ValueError(
                "first_cbm, first_cbm_price, additional_cbm_price required for first_cbm_then_per_cbm"
            )
        if max_weight_kg is None:
            max_weight_kg = 0
        if vol_factor is None or vol_factor <= 0:
            vol_factor = 5000
        config["unit"] = "cbm"
        config["volumetric_weight_factor"] = int(vol_factor)
        config["rules"] = {
            "first_cbm": first_cbm,
            "first_cbm_price": first_cbm_price,
            "additional_cbm_price": additional_cbm_price,
            "max_weight_kg": max_weight_kg,
            "volumetric_factor": vol_factor,
        }
        base_price = first_cbm_price
        price_per_kg = 0

    else:
        raise ValueError(f"Unsupported template: {template_id}")

    # Drop None values from config for cleaner storage
    config = {k: v for k, v in config.items() if v is not None}
    return config, base_price, price_per_kg

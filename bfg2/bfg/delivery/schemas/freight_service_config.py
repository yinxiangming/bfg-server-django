"""
Freight service configuration schema and helpers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bfg.core.schema_convert import (
    pydantic_model_to_config_schema,
    pydantic_model_to_form_schema,
)

_JSON_DEFAULTS: Dict[str, Any] = {
    'rules': {},
    'pricing_rules': [],
    'surcharges': [],
    'discounts': [],
}


def _parse_json_like(value: Any, expected_type: Type, field_name: str) -> Any:
    """Convert textarea JSON strings into structured data."""
    if value is None or value == '':
        return expected_type()
    if isinstance(value, expected_type):
        return value
    if isinstance(value, str):
        template = '{}' if expected_type is dict else '[]'
        raw = value.strip() or template
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name}: invalid JSON ({exc})") from exc
        if not isinstance(parsed, expected_type):
            raise ValueError(f"{field_name}: must be a {expected_type.__name__}")
        return parsed
    raise ValueError(f"{field_name}: must be {expected_type.__name__} or JSON string")


def prepare_freight_config_payload(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Prepare posted config payload by parsing JSON textarea fields.
    Returns a new dict ready for Pydantic validation.
    """
    payload: Dict[str, Any] = dict(data or {})
    for field_name, default in _JSON_DEFAULTS.items():
        expected_type = dict if isinstance(default, dict) else list
        try:
            payload[field_name] = _parse_json_like(payload.get(field_name, default), expected_type, field_name)
        except ValueError as exc:
            # Bubble up with field-specific message
            raise ValueError(str(exc)) from exc
    return payload


class FreightServiceConfigModel(BaseModel):
    """Configuration JSON for FreightService.config."""

    model_config = ConfigDict(extra='allow')

    mode: Literal['linear', 'step', 'tier', 'conditional'] = Field(
        default='linear',
        description='Pricing mode: linear, step, tier, or conditional',
        json_schema_extra={
            'form_type': 'select',
            'options': [
                {'label': 'Linear', 'value': 'linear'},
                {'label': 'Step', 'value': 'step'},
                {'label': 'Tier', 'value': 'tier'},
                {'label': 'Conditional', 'value': 'conditional'},
            ],
        },
    )
    currency: Optional[str] = Field(
        default=None,
        description='Currency code for surcharge/discount calculations (optional)',
        json_schema_extra={'placeholder': 'NZD'},
    )
    unit: str = Field(
        default='kg',
        description='Display unit in billing descriptions (e.g. kg, lb, cbm)',
        json_schema_extra={'placeholder': 'kg'},
    )
    volumetric_weight_factor: Optional[int] = Field(
        default=None,
        ge=0,
        description='Divisor used to convert volume to weight (e.g. 5000)',
        json_schema_extra={'placeholder': '5000'},
    )
    rules: Dict[str, Any] = Field(
        default_factory=dict,
        description='Pricing rules JSON (structure depends on mode)',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 6,
            'placeholder': '{"first_weight":5,"first_price":20,"additional_weight":1,"additional_price":5}',
        },
    )
    pricing_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description='Conditional pricing rules (JSON array, required when mode=conditional)',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 6,
            'placeholder': '[{"priority":1,"conditions":[],"pricing":{}}]',
        },
    )
    surcharges: List[Dict[str, Any]] = Field(
        default_factory=list,
        description='Optional surcharge definitions (JSON array)',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 4,
            'placeholder': '[{"name":"Fuel","type":"rate","value":0.1,"base":"shipping_cost"}]',
        },
    )
    discounts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description='Optional discount definitions (JSON array)',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 4,
            'placeholder': '[{"type":"weight_off","value":1}]',
        },
    )

    @model_validator(mode='after')
    def validate_mode_requirements(self) -> 'FreightServiceConfigModel':
        """Ensure required sections exist based on pricing mode."""
        if self.mode in {'linear', 'step', 'tier'} and not self.rules:
            raise ValueError('rules is required for step/linear/tier modes')
        if self.mode == 'conditional' and not self.pricing_rules:
            raise ValueError('pricing_rules is required when mode=conditional')
        return self


_FREIGHT_CONFIG_SCHEMA = pydantic_model_to_config_schema(FreightServiceConfigModel)
_FREIGHT_FORM_SCHEMA = pydantic_model_to_form_schema(FreightServiceConfigModel, title='Freight Service Configuration')


def get_freight_service_config_schema():
    """Return cached ConfigSchema for freight service config."""
    return _FREIGHT_CONFIG_SCHEMA


def get_freight_service_form_schema():
    """Return cached FormSchema for freight service config."""
    return _FREIGHT_FORM_SCHEMA

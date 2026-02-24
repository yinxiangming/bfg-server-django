"""
Delivery zone schema helpers (non-model JSON fields).
"""

from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bfg.core.schema_convert import pydantic_model_to_form_schema


def _split_csv(value: str) -> List[str]:
    return [item.strip().upper() for item in value.split(',') if item.strip()]


class DeliveryZoneConfigModel(BaseModel):
    """Validate DeliveryZone.countries/postal_code_patterns payloads."""

    model_config = ConfigDict(extra='allow')

    countries: List[str] = Field(
        default_factory=list,
        description='List of ISO alpha-2 country codes',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 2,
            'placeholder': 'NZ, AU, US',
        },
    )
    postal_code_patterns: List[str] = Field(
        default_factory=list,
        description='Optional list of postal code patterns or prefixes',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 2,
            'placeholder': '1010, 20*, 9[0-9]{3}',
        },
    )

    @field_validator('countries', mode='before')
    @classmethod
    def normalize_countries(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = _split_csv(value)
        if not isinstance(value, list):
            raise ValueError('countries must be a list or comma separated string')
        normalized = []
        for code in value:
            code = (code or '').strip().upper()
            if not code:
                continue
            if len(code) != 2:
                raise ValueError(f'Invalid ISO country code: {code}')
            normalized.append(code)
        if not normalized:
            raise ValueError('At least one country is required')
        return normalized

    @field_validator('postal_code_patterns', mode='before')
    @classmethod
    def normalize_patterns(cls, value):
        if value is None or value == '':
            return []
        if isinstance(value, str):
            return _split_csv(value)
        if not isinstance(value, list):
            raise ValueError('postal_code_patterns must be a list or comma separated string')
        return [str(item).strip() for item in value if str(item).strip()]


_DELIVERY_ZONE_FORM_SCHEMA = pydantic_model_to_form_schema(
    DeliveryZoneConfigModel,
    title='Delivery Zone Coverage',
)


def get_delivery_zone_form_schema():
    """Return cached form schema for delivery zone coverage fields."""
    return _DELIVERY_ZONE_FORM_SCHEMA

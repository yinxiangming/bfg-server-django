"""
Carrier configuration schema for delivery module.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from bfg.core.schema_convert import (
    pydantic_model_to_config_schema,
    pydantic_model_to_form_schema,
)


class CarrierConfigModel(BaseModel):
    """Pydantic model for Carrier.config / test_config."""

    model_config = ConfigDict(extra='allow')

    username: Optional[str] = Field(
        default=None,
        description='ParcelPort/legacy username credential',
    )
    password: Optional[str] = Field(
        default=None,
        description='ParcelPort/legacy password credential',
        json_schema_extra={'sensitive': True},
    )
    api_key: Optional[str] = Field(
        default=None,
        description='API key for Starshipit or similar providers',
        json_schema_extra={'sensitive': True},
    )
    subscription_key: Optional[str] = Field(
        default=None,
        description='Subscription key for Starshipit or similar providers',
        json_schema_extra={'sensitive': True},
    )
    client_id: Optional[str] = Field(
        default=None,
        description='Optional client identifier used by some carriers',
    )
    default_pickup_option: Optional[int] = Field(
        default=0,
        ge=0,
        le=1,
        description='Default pickup behavior for ParcelPort (0=book now, 1=schedule later)',
        json_schema_extra={
            'options': [
                {'label': 'Book Now', 'value': 0},
                {'label': 'Schedule Later', 'value': 1},
            ],
            'form_type': 'select',
        },
    )


_CARRIER_CONFIG_SCHEMA = pydantic_model_to_config_schema(CarrierConfigModel)
_CARRIER_FORM_SCHEMA = pydantic_model_to_form_schema(CarrierConfigModel, title='Carrier Configuration')


def get_carrier_config_schema():
    """Return cached ConfigSchema for carrier credentials."""
    return _CARRIER_CONFIG_SCHEMA


def get_carrier_form_schema():
    """Return cached FormSchema for carrier credentials."""
    return _CARRIER_FORM_SCHEMA

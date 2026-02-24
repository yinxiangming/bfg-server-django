"""
DiscountRule.config schema and validation via Pydantic.
Optional advanced config for BOGO / eligibility / future use.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DiscountRuleConfigModel(BaseModel):
    """Pydantic model for DiscountRule.config JSON."""

    model_config = ConfigDict(extra='allow')

    min_quantity: Optional[int] = Field(
        default=None,
        ge=0,
        description='Minimum quantity for eligibility (BOGO / product rules)',
    )
    max_uses_per_customer: Optional[int] = Field(
        default=None,
        ge=0,
        description='Max times a customer can use this rule (optional)',
    )
    max_uses_total: Optional[int] = Field(
        default=None,
        ge=0,
        description='Max total redemptions (optional)',
    )



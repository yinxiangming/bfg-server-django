"""
Campaign.config schema and validation via Pydantic.
Config types: stamp_card, weekly_streak, tiered_spend, issue_coupon_on_join (join-only).
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CampaignConfigModel(BaseModel):
    """Pydantic model for Campaign.config JSON."""

    model_config = ConfigDict(extra='allow')

    type: Literal['', 'stamp_card', 'weekly_streak', 'tiered_spend'] = Field(
        default='',
        description='Campaign config type: stamp_card, weekly_streak, tiered_spend, or empty',
    )
    stamps_required: Optional[int] = Field(
        default=None,
        ge=1,
        description='Number of stamps required to redeem (stamp_card)',
    )
    streak_weeks: Optional[int] = Field(
        default=None,
        ge=1,
        description='Consecutive weeks with at least one purchase to redeem (weekly_streak)',
    )
    reward_type: Literal['coupon', 'gift_card'] = Field(
        default='coupon',
        description='Reward on redeem: coupon or gift_card',
    )
    discount_rule_id: Optional[int] = Field(
        default=None,
        description='DiscountRule PK for coupon reward or join-issued coupon',
    )
    reward_value: Optional[float] = Field(
        default=None,
        gt=0,
        description='Gift card amount when reward_type is gift_card',
    )
    issue_coupon_on_join: bool = Field(
        default=False,
        description='Issue a coupon when customer joins campaign',
    )

    @model_validator(mode='after')
    def type_specific_required(self) -> 'CampaignConfigModel':
        if self.type == 'stamp_card' and self.stamps_required is None:
            raise ValueError('stamps_required is required for type stamp_card')
        if self.type == 'weekly_streak' and self.streak_weeks is None:
            raise ValueError('streak_weeks is required for type weekly_streak')
        if self.reward_type == 'gift_card' and (self.reward_value is None or self.reward_value <= 0):
            raise ValueError('reward_value must be positive when reward_type is gift_card')
        return self



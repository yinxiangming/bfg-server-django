"""
Marketing config schemas for Campaign.config and DiscountRule.config.
CampaignDisplay.rules reuses bfg.shop.schemas (CategoryRuleModel / ProductCategoryRulesModel).
"""

from bfg.marketing.schemas.campaign_config import CampaignConfigModel
from bfg.marketing.schemas.discount_rule_config import DiscountRuleConfigModel

__all__ = [
    'CampaignConfigModel',
    'DiscountRuleConfigModel',
]

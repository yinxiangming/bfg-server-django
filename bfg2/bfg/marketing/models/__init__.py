# -*- coding: utf-8 -*-
"""
Marketing models package.
Unified exports for backward compatibility: from bfg.marketing.models import X
"""

from .base import (
    CampaignGroup,
    Campaign,
    CampaignParticipation,
    DiscountRule,
    Coupon,
    StampRecord,
    ReferralProgram,
    Referral,
    Channel,
    ChannelLink,
    LinkClick,
    AffiliatePartner,
    CampaignAnalytics,
)
from .gift_card import GiftCard
from .promo_display import CampaignDisplay

__all__ = [
    'CampaignGroup',
    'Campaign',
    'CampaignParticipation',
    'DiscountRule',
    'Coupon',
    'StampRecord',
    'ReferralProgram',
    'Referral',
    'Channel',
    'ChannelLink',
    'LinkClick',
    'AffiliatePartner',
    'CampaignAnalytics',
    'GiftCard',
    'CampaignDisplay',
]

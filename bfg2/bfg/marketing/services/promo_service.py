"""
BFG Promo Module Services

Coupon and Campaign services
"""

from typing import Any, Optional
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from bfg.core.services import BaseService
from bfg.marketing.models import (
    Coupon,
    Campaign,
    CampaignParticipation,
    DiscountRule,
    Referral,
    StampRecord,
)
from bfg.marketing.models import GiftCard
from bfg.common.models import Customer
from bfg.shop.models import Order


class CouponService(BaseService):
    """Coupon management and validation service"""
    
    def validate_coupon(
        self,
        code: str,
        customer: Customer,
        order_total: Decimal
    ) -> tuple[bool, Optional[str], Optional[Decimal]]:
        """
        Validate coupon code
        
        Returns:
            tuple: (is_valid, error_message, discount_amount)
        """
        try:
            coupon = Coupon.objects.get(
                workspace=self.workspace,
                code=code,
                is_active=True
            )
        except Coupon.DoesNotExist:
            return (False, "Invalid coupon code", None)
        
        # Check validity period
        now = timezone.now()
        if coupon.valid_from > now:
            return (False, "Coupon not yet valid", None)
        if coupon.valid_until and coupon.valid_until < now:
            return (False, "Coupon has expired", None)
        
        # Check usage limits
        if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
            return (False, "Coupon usage limit reached", None)
        
        # Calculate discount
        discount = self._calculate_discount(coupon.discount_rule, order_total)
        
        return (True, None, discount)
    
    def _calculate_discount(
        self,
        rule: DiscountRule,
        amount: Decimal
    ) -> Decimal:
        """Calculate discount amount"""
        if rule.discount_type == 'percentage':
            discount = (amount * rule.discount_value) / Decimal('100')
        else:  # fixed_amount
            discount = rule.discount_value
        
        # Apply maximum discount
        if rule.maximum_discount:
            discount = min(discount, rule.maximum_discount)
        
        return discount


class CampaignService(BaseService):
    """Campaign management service"""

    @transaction.atomic
    def create_campaign(
        self,
        name: str,
        campaign_type: str,
        start_date,
        **kwargs: Any
    ) -> Campaign:
        """Create marketing campaign"""
        campaign = Campaign.objects.create(
            workspace=self.workspace,
            name=name,
            campaign_type=campaign_type,
            start_date=start_date,
            end_date=kwargs.get('end_date'),
            description=kwargs.get('description', ''),
            is_active=True,
            created_by=self.user,
        )
        return campaign

    @transaction.atomic
    def join_campaign(
        self,
        customer: Customer,
        campaign: Campaign,
        *,
        issue_coupon: bool = False,
        discount_rule_id: Optional[int] = None,
    ) -> tuple[CampaignParticipation, Optional[Coupon]]:
        """
        Register customer participation in a campaign (Boost). Optionally issue a coupon.

        Returns:
            (participation, coupon or None)
        """
        now = timezone.now()
        if not campaign.is_active:
            raise ValueError("Campaign is not active")
        if campaign.start_date > now:
            raise ValueError("Campaign has not started")
        if campaign.end_date and campaign.end_date < now:
            raise ValueError("Campaign has ended")
        if campaign.max_participants is not None:
            current = campaign.participations.count()
            if current >= campaign.max_participants:
                raise ValueError("Campaign participation limit reached")

        participation = CampaignParticipation.objects.create(
            workspace=self.workspace,
            campaign=campaign,
            customer=customer,
            status='registered',
        )

        coupon = None
        config = getattr(campaign, 'config', None) or {}
        rule_id = discount_rule_id or config.get('discount_rule_id')
        should_issue = issue_coupon or config.get('issue_coupon_on_join', False)

        if should_issue and rule_id:
            try:
                rule = DiscountRule.objects.get(
                    workspace=self.workspace,
                    pk=rule_id,
                    is_active=True,
                )
            except DiscountRule.DoesNotExist:
                pass
            else:
                coupon = Coupon.objects.create(
                    workspace=self.workspace,
                    campaign=campaign,
                    discount_rule=rule,
                    boost=participation,
                    code=self._generate_join_coupon_code(customer, campaign),
                    valid_from=now,
                    valid_until=campaign.end_date,
                    is_active=True,
                )
                participation.status = 'coupon_issued'
                participation.save(update_fields=['status', 'updated_at'])

        return participation, coupon

    def _generate_join_coupon_code(self, customer: Customer, campaign: Campaign) -> str:
        """Generate a unique code for join-issued coupon."""
        import secrets
        base = f"JOIN{campaign.id:04d}{customer.id:06d}"
        while True:
            code = f"{base}{secrets.token_hex(2).upper()}"
            if not Coupon.objects.filter(workspace=self.workspace, code=code).exists():
                return code


class StampService(BaseService):
    """Stamp / redemption service for stamp_card and weekly_streak campaigns."""

    def get_stamp_progress(
        self,
        customer: Customer,
        campaign: Campaign,
    ) -> dict:
        """
        Return current progress for stamp/redeem campaigns.
        Keys: stamps_count, week_filled (list of week_index with >=1 stamp), can_redeem, already_redeemed, config.
        """
        config = getattr(campaign, 'config', None) or {}
        ctype = config.get('type', '')
        stamps_required = config.get('stamps_required', 0)
        streak_weeks = config.get('streak_weeks', 0)

        stamps = StampRecord.objects.filter(
            workspace=self.workspace,
            campaign=campaign,
            customer=customer,
            record_type='stamp',
        )
        redemptions = StampRecord.objects.filter(
            workspace=self.workspace,
            campaign=campaign,
            customer=customer,
            record_type='redemption',
        )

        if ctype == 'weekly_streak' and streak_weeks:
            week_filled = list(
                stamps.exclude(week_index__isnull=True)
                .values_list('week_index', flat=True)
                .distinct()
            )
            week_filled = [w for w in week_filled if 1 <= w <= streak_weeks]
            already_redeemed = redemptions.exists()
            can_redeem = not already_redeemed and len(week_filled) >= streak_weeks
            return {
                'stamps_count': stamps.count(),
                'week_filled': sorted(week_filled),
                'streak_weeks': streak_weeks,
                'can_redeem': can_redeem,
                'already_redeemed': already_redeemed,
                'config': config,
            }
        # stamp_card or default: count stamps in current period
        stamps_count = stamps.count()
        already_redeemed = redemptions.exists()
        can_redeem = not already_redeemed and stamps_required and stamps_count >= stamps_required
        return {
            'stamps_count': stamps_count,
            'stamps_required': stamps_required,
            'can_redeem': can_redeem,
            'already_redeemed': already_redeemed,
            'config': config,
        }

    @transaction.atomic
    def redeem(
        self,
        customer: Customer,
        campaign: Campaign,
    ) -> tuple[Optional[StampRecord], Optional[Coupon], Optional[GiftCard]]:
        """
        Redeem reward if eligible. Returns (redemption_record, coupon_or_none, gift_card_or_none).
        """
        progress = self.get_stamp_progress(customer, campaign)
        if not progress.get('can_redeem'):
            raise ValueError("Not eligible to redeem")
        config = progress.get('config') or {}
        reward_type = config.get('reward_type', 'coupon')
        discount_rule_id = config.get('discount_rule_id')
        reward_value = config.get('reward_value')  # for gift card amount

        redemption_record = None
        coupon = None
        gift_card = None
        now = timezone.now()

        if reward_type == 'gift_card' and reward_value:
            from bfg.finance.models import Currency
            currency = Currency.objects.filter(workspace=self.workspace).first()
            if currency:
                gift_card = GiftCard.objects.create(
                    workspace=self.workspace,
                    customer=customer,
                    initial_value=reward_value,
                    balance=reward_value,
                    currency=currency,
                    is_active=True,
                )
        elif discount_rule_id:
            try:
                rule = DiscountRule.objects.get(
                    workspace=self.workspace,
                    pk=discount_rule_id,
                    is_active=True,
                )
            except DiscountRule.DoesNotExist:
                raise ValueError("Reward discount rule not found")
            code = f"STAMP{campaign.id:04d}{customer.id:06d}{now.strftime('%H%M%S')}"
            coupon = Coupon.objects.create(
                workspace=self.workspace,
                campaign=campaign,
                discount_rule=rule,
                code=code,
                valid_from=now,
                valid_until=campaign.end_date,
                is_active=True,
            )

        redemption_record = StampRecord.objects.create(
            workspace=self.workspace,
            campaign=campaign,
            customer=customer,
            record_type='redemption',
            reward_coupon=coupon,
            reward_gift_card=gift_card,
        )
        return redemption_record, coupon, gift_card

    def record_stamp(
        self,
        customer: Customer,
        campaign: Campaign,
        order: Order,
        order_item=None,
        period_start=None,
        period_end=None,
        week_index: Optional[int] = None,
    ) -> StampRecord:
        """Record one stamp (qualifying purchase). Called after order is paid/completed."""
        return StampRecord.objects.create(
            workspace=self.workspace,
            campaign=campaign,
            customer=customer,
            record_type='stamp',
            order=order,
            order_item=order_item,
            period_start=period_start,
            period_end=period_end,
            week_index=week_index,
        )

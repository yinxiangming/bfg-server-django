"""
BFG Promo Module Serializers
"""

from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers

from bfg.core.schema_convert import validation_error_to_message
from bfg.marketing.schemas import CampaignConfigModel, DiscountRuleConfigModel
from bfg.shop.schemas import prepare_category_rules_value, ProductCategoryRulesModel
from bfg.marketing.models import (
    Campaign,
    CampaignDisplay,
    CampaignParticipation,
    Coupon,
    CampaignGroup,
    DiscountRule,
    GiftCard,
    ReferralProgram,
    StampRecord,
)


class CampaignGroupSerializer(serializers.ModelSerializer):
    """Campaign group serializer"""
    
    class Meta:
        model = CampaignGroup
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'updated_at']


class DiscountRuleSerializer(serializers.ModelSerializer):
    """Discount rule serializer"""

    class Meta:
        model = DiscountRule
        fields = [
            'id', 'name', 'discount_type', 'discount_value', 'apply_to', 'is_active', 'config',
            'valid_from', 'valid_until', 'display_label', 'promo_display_order', 'is_group_buy',
        ]

    def validate_config(self, value):
        """Validate DiscountRule.config against schema."""
        if value is None:
            return {}
        try:
            DiscountRuleConfigModel.model_validate(value)
        except PydanticValidationError as e:
            raise serializers.ValidationError(validation_error_to_message(e))
        return value

    def validate_discount_value(self, value):
        """Validate discount_value is positive"""
        from decimal import Decimal
        if value is None:
            raise serializers.ValidationError("Discount value is required")
        if isinstance(value, (int, float, str)):
            value = Decimal(str(value))
        if value < 0:
            raise serializers.ValidationError("Discount value cannot be negative")
        # For percentage discounts, value should be between 0 and 100
        # For fixed discounts, value should be reasonable (e.g., < 999999)
        if value > 999999:
            raise serializers.ValidationError("Discount value cannot exceed 999999")
        return value


class CampaignSerializer(serializers.ModelSerializer):
    """Campaign serializer"""
    group = CampaignGroupSerializer(read_only=True)
    group_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'campaign_type', 'description',
            'start_date', 'end_date', 'budget',
            'utm_source', 'utm_medium', 'utm_campaign',
            'is_active', 'created_at', 'updated_at',
            'group', 'group_id', 'created_by_username',
            'requires_participation', 'min_participants', 'max_participants', 'promo_display_type',
            'config',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_config(self, value):
        """Validate Campaign.config against schema."""
        if value is None:
            return {}
        try:
            CampaignConfigModel.model_validate(value)
        except PydanticValidationError as e:
            raise serializers.ValidationError(validation_error_to_message(e))
        return value

    def validate_budget(self, value):
        """Validate budget is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Budget cannot be negative")
        return value


class CampaignParticipationSerializer(serializers.ModelSerializer):
    """Campaign participation (Boost) serializer."""
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = CampaignParticipation
        fields = [
            'id', 'campaign', 'campaign_name', 'customer', 'status',
            'created_at', 'updated_at', 'order',
        ]
        read_only_fields = ['created_at', 'updated_at']


class CampaignDisplaySerializer(serializers.ModelSerializer):
    """Campaign display (slide, featured category/post) serializer. Campaign optional; rules for product/category selection."""
    campaign_name = serializers.SerializerMethodField()
    link_url = serializers.CharField(required=False, allow_blank=True, max_length=500)

    class Meta:
        model = CampaignDisplay
        fields = [
            'id', 'workspace', 'campaign', 'campaign_name', 'display_type', 'order',
            'title', 'subtitle',
            'image', 'link_url', 'link_target',
            'rules', 'post', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_campaign_name(self, obj):
        return obj.campaign.name if obj.campaign_id else None

    def validate_rules(self, value):
        """Validate with same schema as ProductCategory.rules (CategoryRuleModel)."""
        try:
            normalized = prepare_category_rules_value(value)
            ProductCategoryRulesModel.model_validate({'rules': normalized})
            return normalized
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        except PydanticValidationError as e:
            raise serializers.ValidationError(validation_error_to_message(e))

    def validate(self, attrs):
        campaign = attrs.get('campaign') or (self.instance.campaign if self.instance else None)
        workspace = attrs.get('workspace') or (self.instance.workspace_id if self.instance else None)
        if not campaign and not workspace:
            raise serializers.ValidationError({'workspace': 'Either campaign or workspace is required.'})
        return attrs

    def save(self, **kwargs):
        if self.validated_data.get('campaign'):
            kwargs['workspace_id'] = self.validated_data['campaign'].workspace_id
        elif self.validated_data.get('workspace'):
            w = self.validated_data['workspace']
            kwargs['workspace_id'] = getattr(w, 'id', w)
        return super().save(**kwargs)


class StampRecordSerializer(serializers.ModelSerializer):
    """Stamp record (stamp / redemption) serializer."""
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = StampRecord
        fields = [
            'id', 'campaign', 'campaign_name', 'customer', 'record_type',
            'order', 'order_item', 'reward_coupon', 'reward_gift_card',
            'period_start', 'period_end', 'week_index', 'created_at',
        ]
        read_only_fields = ['created_at']


class CouponSerializer(serializers.ModelSerializer):
    """Coupon serializer"""
    campaign = CampaignSerializer(read_only=True)
    campaign_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    discount_rule = DiscountRuleSerializer(read_only=True)
    discount_rule_id = serializers.IntegerField(write_only=True)
    boost_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = Coupon
        fields = [
            'id', 'code', 'description',
            'usage_limit', 'usage_limit_per_customer', 'times_used',
            'valid_from', 'valid_until',
            'is_active', 'created_at', 'updated_at',
            'campaign', 'campaign_id', 'discount_rule', 'discount_rule_id',
            'boost', 'boost_id',
        ]
        read_only_fields = ['created_at', 'updated_at', 'times_used']
    
    def validate_usage_limit(self, value):
        """Validate usage_limit is non-negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Usage limit cannot be negative")
        return value
    
    def validate_usage_limit_per_customer(self, value):
        """Validate usage_limit_per_customer is non-negative"""
        if value is not None and value < 0:
            raise serializers.ValidationError("Usage limit per customer cannot be negative")
        return value


class GiftCardSerializer(serializers.ModelSerializer):
    """Gift card serializer"""
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    customer_name = serializers.SerializerMethodField()
    
    class Meta:
        model = GiftCard
        fields = [
            'id', 'code', 'initial_value', 'balance', 'currency',
            'currency_code', 'customer', 'customer_name', 'is_active',
            'expires_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'code', 'created_at', 'updated_at']
    
    def get_customer_name(self, obj):
        """Get customer full name"""
        if obj.customer and obj.customer.user:
            return obj.customer.user.get_full_name()
        return None
    
    def validate_initial_value(self, value):
        """Validate initial_value is positive"""
        from decimal import Decimal
        if value is None:
            raise serializers.ValidationError("Initial value is required")
        if isinstance(value, (int, float, str)):
            value = Decimal(str(value))
        if value <= 0:
            raise serializers.ValidationError("Initial value must be greater than 0")
        if value > 999999.99:
            raise serializers.ValidationError("Initial value cannot exceed 999999.99")
        return value
    
    def validate_balance(self, value):
        """Validate balance is non-negative and doesn't exceed initial_value"""
        from decimal import Decimal
        if value is None:
            return value
        if isinstance(value, (int, float, str)):
            value = Decimal(str(value))
        if value < 0:
            raise serializers.ValidationError("Balance cannot be negative")
        # Check if balance exceeds initial_value (if initial_value is set)
        if hasattr(self, 'initial_data') and 'initial_value' in self.initial_data:
            initial_value = Decimal(str(self.initial_data['initial_value']))
            if value > initial_value:
                raise serializers.ValidationError("Balance cannot exceed initial value")
        return value


class ReferralProgramSerializer(serializers.ModelSerializer):
    """Referral program serializer"""
    
    class Meta:
        model = ReferralProgram
        fields = [
            'id', 'name', 'description', 'referrer_reward', 'referee_reward',
            'minimum_purchase', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_referrer_reward(self, value):
        """Validate referrer_reward is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Referrer reward cannot be negative")
        return value
    
    def validate_referee_reward(self, value):
        """Validate referee_reward is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Referee reward cannot be negative")
        return value
    
    def validate_minimum_purchase(self, value):
        """Validate minimum_purchase is non-negative"""
        from decimal import Decimal
        if value is not None:
            if isinstance(value, (int, float, str)):
                value = Decimal(str(value))
            if value < 0:
                raise serializers.ValidationError("Minimum purchase cannot be negative")
        return value


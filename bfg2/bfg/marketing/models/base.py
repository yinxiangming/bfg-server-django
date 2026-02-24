# -*- coding: utf-8 -*-
"""
Base models for BFG Promo module.
Marketing campaigns, coupons, referrals, and affiliate programs.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from decimal import Decimal


class CampaignGroup(models.Model):
    """Campaign group for organizing campaigns."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='campaign_groups')

    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True)

    is_active = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Campaign Group")
        verbose_name_plural = _("Campaign Groups")
        ordering = ['name']

    def __str__(self):
        return self.name


class Campaign(models.Model):
    """Marketing campaign."""
    CAMPAIGN_TYPE_CHOICES = (
        ('email', _('Email')),
        ('sms', _('SMS')),
        ('social', _('Social Media')),
        ('affiliate', _('Affiliate')),
        ('other', _('Other')),
    )

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='campaigns')
    group = models.ForeignKey(CampaignGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='campaigns')

    name = models.CharField(_("Name"), max_length=255)
    campaign_type = models.CharField(_("Type"), max_length=20, choices=CAMPAIGN_TYPE_CHOICES)
    description = models.TextField(_("Description"), blank=True)

    # Dates
    start_date = models.DateTimeField(_("Start Date"))
    end_date = models.DateTimeField(_("End Date"), null=True, blank=True)

    # Budget
    budget = models.DecimalField(_("Budget"), max_digits=10, decimal_places=2, null=True, blank=True)

    # Tracking
    utm_source = models.CharField(_("UTM Source"), max_length=100, blank=True)
    utm_medium = models.CharField(_("UTM Medium"), max_length=100, blank=True)
    utm_campaign = models.CharField(_("UTM Campaign"), max_length=100, blank=True)

    is_active = models.BooleanField(_("Active"), default=True)

    # Participation-type campaigns (e.g. group buy)
    requires_participation = models.BooleanField(_("Requires Participation"), default=False)
    min_participants = models.PositiveIntegerField(_("Min Participants"), null=True, blank=True)
    max_participants = models.PositiveIntegerField(_("Max Participants"), null=True, blank=True)
    promo_display_type = models.CharField(_("Promo Display Type"), max_length=50, blank=True)

    # Flexible config for stamp_card, weekly_streak, tiered_spend, issue_coupon_on_join, etc.
    config = models.JSONField(_("Configuration"), default=dict, blank=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='campaigns_created')

    class Meta:
        verbose_name = _("Campaign")
        verbose_name_plural = _("Campaigns")
        ordering = ['-start_date']

    def __str__(self):
        return self.name


class CampaignParticipation(models.Model):
    """Customer participation in a campaign (Boost). Links customer to campaign and optional coupon."""
    STATUS_CHOICES = (
        ('registered', _('Registered')),
        ('qualified', _('Qualified')),
        ('coupon_issued', _('Coupon Issued')),
        ('redeemed', _('Redeemed')),
    )

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='campaign_participations')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='participations')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='campaign_participations')

    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='registered')
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    order = models.ForeignKey('shop.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = _("Campaign Participation")
        verbose_name_plural = _("Campaign Participations")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer} in {self.campaign.name}"


class DiscountRule(models.Model):
    """Discount rule for campaigns and coupons."""
    DISCOUNT_TYPE_CHOICES = (
        ('percentage', _('Percentage')),
        ('fixed_amount', _('Fixed Amount')),
        ('free_shipping', _('Free Shipping')),
        ('buy_x_get_y', _('Buy X Get Y')),
        ('other', _('Other')),
    )

    APPLY_TO_CHOICES = (
        ('order', _('Entire Order')),
        ('products', _('Specific Products')),
        ('categories', _('Specific Categories')),
        ('other', _('Other')),
    )

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='discount_rules')

    name = models.CharField(_("Name"), max_length=255)

    # Discount
    discount_type = models.CharField(_("Discount Type"), max_length=20, choices=DISCOUNT_TYPE_CHOICES)
    discount_value = models.DecimalField(_("Discount Value"), max_digits=10, decimal_places=2)

    # Application
    apply_to = models.CharField(_("Apply To"), max_length=20, choices=APPLY_TO_CHOICES, default='order')
    products = models.ManyToManyField('shop.Product', blank=True, related_name='discount_rules')
    categories = models.ManyToManyField('shop.ProductCategory', blank=True, related_name='discount_rules')

    # Conditions
    minimum_purchase = models.DecimalField(_("Minimum Purchase"), max_digits=10, decimal_places=2, null=True, blank=True)
    maximum_discount = models.DecimalField(_("Maximum Discount"), max_digits=10, decimal_places=2, null=True, blank=True)

    # Advanced Configuration (Eligibility, etc.)
    config = models.JSONField(_("Configuration"), default=dict, blank=True)

    # BOGO / Advanced Logic
    # Prerequisite (Buy X)
    prerequisite_quantity = models.PositiveIntegerField(_("Prerequisite Quantity"), null=True, blank=True)
    prerequisite_product_ids = models.JSONField(_("Prerequisite Product IDs"), default=list, blank=True)

    # Entitlement (Get Y)
    entitled_quantity = models.PositiveIntegerField(_("Entitled Quantity"), null=True, blank=True)
    entitled_product_ids = models.JSONField(_("Entitled Product IDs"), default=list, blank=True)

    allocation_method = models.CharField(
        _("Allocation Method"),
        max_length=20,
        choices=[('each', _('Each')), ('across', _('Across'))],
        default='each'
    )

    # Optional display / time window for frontend (does not affect discount calculation)
    valid_from = models.DateTimeField(_("Valid From"), null=True, blank=True)
    valid_until = models.DateTimeField(_("Valid Until"), null=True, blank=True)
    display_label = models.CharField(_("Display Label"), max_length=255, blank=True)
    promo_display_order = models.PositiveSmallIntegerField(_("Promo Display Order"), null=True, blank=True)
    is_group_buy = models.BooleanField(_("Is Group Buy"), default=False)

    is_active = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Discount Rule")
        verbose_name_plural = _("Discount Rules")
        ordering = ['name']

    def __str__(self):
        return self.name


class Coupon(models.Model):
    """Discount coupon."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='coupons')
    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name='coupons')
    discount_rule = models.ForeignKey(DiscountRule, on_delete=models.PROTECT, related_name='coupons')
    boost = models.ForeignKey(
        CampaignParticipation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coupons'
    )

    code = models.CharField(_("Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)

    # Usage limits
    usage_limit = models.PositiveIntegerField(_("Usage Limit"), null=True, blank=True)  # Total uses
    usage_limit_per_customer = models.PositiveIntegerField(_("Usage Limit per Customer"), null=True, blank=True)
    times_used = models.PositiveIntegerField(_("Times Used"), default=0)

    # Dates
    valid_from = models.DateTimeField(_("Valid From"))
    valid_until = models.DateTimeField(_("Valid Until"), null=True, blank=True)

    is_active = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Coupon")
        verbose_name_plural = _("Coupons")
        ordering = ['-created_at']
        unique_together = ('workspace', 'code')

    def __str__(self):
        return self.code


class StampRecord(models.Model):
    """Stamp/check-in and redemption record for stamp_card and weekly_streak campaigns."""
    RECORD_TYPE_CHOICES = (
        ('stamp', _('Stamp')),
        ('redemption', _('Redemption')),
    )

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='stamp_records')
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='stamp_records')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='stamp_records')

    record_type = models.CharField(_("Record Type"), max_length=20, choices=RECORD_TYPE_CHOICES)
    order = models.ForeignKey('shop.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    order_item = models.ForeignKey('shop.OrderItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    reward_coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reward_gift_card = models.ForeignKey(
        'GiftCard',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    period_start = models.DateTimeField(_("Period Start"), null=True, blank=True)
    period_end = models.DateTimeField(_("Period End"), null=True, blank=True)
    week_index = models.PositiveSmallIntegerField(_("Week Index"), null=True, blank=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Stamp Record")
        verbose_name_plural = _("Stamp Records")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.record_type} {self.customer_id} #{self.campaign_id}"


class ReferralProgram(models.Model):
    """Referral program configuration."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='referral_programs')

    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True)

    # Rewards
    referrer_reward = models.DecimalField(_("Referrer Reward"), max_digits=10, decimal_places=2)
    referee_reward = models.DecimalField(_("Referee Reward"), max_digits=10, decimal_places=2)

    # Conditions
    minimum_purchase = models.DecimalField(_("Minimum Purchase"), max_digits=10, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Referral Program")
        verbose_name_plural = _("Referral Programs")

    def __str__(self):
        return self.name


class Referral(models.Model):
    """Customer referral."""
    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('completed', _('Completed')),
        ('rewarded', _('Rewarded')),
    )

    program = models.ForeignKey(ReferralProgram, on_delete=models.CASCADE, related_name='referrals')
    referrer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='referrals_made')
    referee = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='referrals_received')

    referral_code = models.CharField(_("Referral Code"), max_length=50, unique=True)

    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')

    # Reward tracking
    referrer_rewarded = models.BooleanField(_("Referrer Rewarded"), default=False)
    referee_rewarded = models.BooleanField(_("Referee Rewarded"), default=False)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    completed_at = models.DateTimeField(_("Completed At"), null=True, blank=True)

    class Meta:
        verbose_name = _("Referral")
        verbose_name_plural = _("Referrals")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.referrer} → {self.referee}"


class Channel(models.Model):
    """Marketing channel."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='channels')

    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50)
    description = models.TextField(_("Description"), blank=True)

    is_active = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Channel")
        verbose_name_plural = _("Channels")
        ordering = ['name']
        unique_together = ('workspace', 'code')

    def __str__(self):
        return self.name


class ChannelLink(models.Model):
    """Tracking link for a channel."""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='links')
    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name='links')

    url = models.URLField(_("URL"), max_length=500)
    tracking_code = models.CharField(_("Tracking Code"), max_length=100, unique=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Channel Link")
        verbose_name_plural = _("Channel Links")

    def __str__(self):
        return f"{self.channel.name} - {self.tracking_code}"


class LinkClick(models.Model):
    """Click tracking for channel links."""
    link = models.ForeignKey(ChannelLink, on_delete=models.CASCADE, related_name='clicks')

    # Request info
    ip_address = models.GenericIPAddressField(_("IP Address"), null=True, blank=True)
    user_agent = models.TextField(_("User Agent"), blank=True)
    referer = models.URLField(_("Referer"), max_length=500, blank=True)

    # Customer (if logged in)
    customer = models.ForeignKey('common.Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='link_clicks')

    clicked_at = models.DateTimeField(_("Clicked At"), default=timezone.now)

    class Meta:
        verbose_name = _("Link Click")
        verbose_name_plural = _("Link Clicks")
        ordering = ['-clicked_at']

    def __str__(self):
        return f"{self.link.tracking_code} @ {self.clicked_at}"


class AffiliatePartner(models.Model):
    """Affiliate partner."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='affiliate_partners')

    name = models.CharField(_("Name"), max_length=255)
    code = models.CharField(_("Code"), max_length=50, unique=True)
    email = models.EmailField(_("Email"))

    # Commission
    commission_rate = models.DecimalField(_("Commission Rate %"), max_digits=5, decimal_places=2)

    is_active = models.BooleanField(_("Active"), default=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Affiliate Partner")
        verbose_name_plural = _("Affiliate Partners")
        ordering = ['name']

    def __str__(self):
        return self.name


class CampaignAnalytics(models.Model):
    """Campaign performance analytics."""
    campaign = models.OneToOneField(Campaign, on_delete=models.CASCADE, related_name='analytics')

    # Metrics
    impressions = models.PositiveIntegerField(_("Impressions"), default=0)
    clicks = models.PositiveIntegerField(_("Clicks"), default=0)
    conversions = models.PositiveIntegerField(_("Conversions"), default=0)
    revenue = models.DecimalField(_("Revenue"), max_digits=12, decimal_places=2, default=Decimal('0'))

    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Campaign Analytics")
        verbose_name_plural = _("Campaign Analytics")

    def __str__(self):
        return f"Analytics for {self.campaign.name}"

    @property
    def ctr(self):
        """Click-through rate."""
        return (self.clicks / self.impressions * 100) if self.impressions > 0 else 0

    @property
    def conversion_rate(self):
        """Conversion rate."""
        return (self.conversions / self.clicks * 100) if self.clicks > 0 else 0

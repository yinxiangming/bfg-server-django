# BFG2_PROMO Module - Marketing & Promotions

## Overview

The `bfg.marketing` module provides campaign management, coupons, discount rules, referrals, and multi-channel tracking. The design separates **Campaign** (activity), **DiscountRule** (how to calculate discount), and **Coupon** (code + validity + optional link to participation); **CampaignParticipation (Boost)** represents "customer joined a campaign" and **CampaignDisplay** unifies homepage/slide/featured content.

## Current Design Summary

### Model Relationships

- **Campaign** – Defines the activity (time window, budget, UTM). No discount fields; discount logic lives in DiscountRule.
- **DiscountRule** – Standalone "discount engine" (percentage, fixed, products/categories, min/max). Reusable by many Coupons. **Not** tied to a single Campaign.
- **Coupon** – Links a **DiscountRule** (required) and optionally a **Campaign**; has code, valid_from/valid_until, usage_limit. Optional **boost_id** (FK to CampaignParticipation): when set, this coupon was issued as the **entitlement** for that participation.
- **CampaignParticipation (Boost)** – "Customer joined this campaign." One record per customer per campaign participation; status e.g. registered, qualified, coupon_issued, redeemed. When a coupon is issued because of participation, `coupon.boost_id` points to this record.
- **CampaignDisplay** – One record per "display block" of a campaign: slide (image + link), featured_category (ProductCategory), or featured_post (Post + optional image). Used for homepage carousel, featured categories, and featured posts.

### Why Coupon and DiscountRule Are Separate

- **Reuse**: One DiscountRule (e.g. "10% off product X") can back many Coupons (different codes, campaigns, or validity).
- **Single responsibility**: DiscountRule = how to compute discount; Coupon = who/when/how many times (code, validity, usage limits).
- **Campaign-agnostic rules**: Rules can be shared across campaigns or used without a campaign.

### Why CampaignParticipation (Boost)

- **Explicit "participation"**: "Customer joined campaign X" is a first-class record (Boost), not inferred from coupon usage.
- **Coupon as entitlement**: Coupons issued from a Boost have `boost_id` set; they are the **proof** that the customer can use that campaign's offer. Flow: join campaign → create Boost → issue Coupon (boost_id = Boost) → customer uses Coupon at checkout; DiscountRule does the calculation.

### Business Narrative (Example)

"We create a Campaign (e.g. Double 11). Customer Xiao Wang clicks Join; the system creates a **CampaignParticipation** (Boost) for him. Based on that participation, the system issues a **Coupon** (with boost_id pointing to that Boost) as his entitlement. When Xiao Wang checks out with that Coupon, the system uses the Coupon's **DiscountRule** to compute the discount (e.g. 10 CNY off)."

### API (Current / Planned)

- **Join campaign**: `POST /api/.../campaigns/{id}/join/` → creates CampaignParticipation, optionally issues Coupon (boost_id set). Service: `join_campaign(customer, campaign)`.
- **Campaign displays**: `GET /api/storefront/promo/` or `campaigns/{id}/displays/` → CampaignDisplay by display_type (slide, featured_category, featured_post).
- **Coupons / DiscountRule**: Existing endpoints; order calculation unchanged.

---

## Models (Reference)

*Below: legacy/reference structure. Actual `bfg.marketing.models` use Campaign (no discount fields), DiscountRule (standalone, products/categories M2M), Coupon (campaign_id optional, discount_rule_id required, boost_id optional), plus CampaignParticipation and CampaignDisplay.*

### CampaignGroup

**Purpose**: Organize campaigns into groups.

**Migrated from**: `freight/models/promotions.py`

```python
class CampaignGroup(models.Model):
    """
    Campaign group for organizing related campaigns.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.ImageField(upload_to='campaign_groups/', blank=True)
    
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Campaign

**Purpose**: Marketing campaign with discount/promotion rules.

**Migrated from**: `freight/models/promotions.py`

```python
class Campaign(models.Model):
    """
    Marketing campaign.
    """
    TRIGGER_TYPE_CHOICES = (
        ('manual', 'Manual'),
        ('auto', 'Automatic'),
        ('register', 'On Registration'),
        ('first_order', 'First Order'),
        ('cart_abandonment', 'Cart Abandonment'),
    )
    
    DISCOUNT_TYPE_CHOICES = (
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
        ('free_shipping', 'Free Shipping'),
        ('bogo', 'Buy One Get One'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    group = models.ForeignKey(CampaignGroup, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Basic Info
    title = models.CharField(max_length=100)
    code = models.CharField(max_length=50)  # Internal code
    description = models.TextField(blank=True)
    
    # Discount rules
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default='percentage')
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Conditions
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Applicable products
    applicable_products = models.ManyToManyField('bfg2_shop.Product', blank=True)
    applicable_categories = models.ManyToManyField('bfg2_shop.ProductCategory', blank=True)
    exclude_sale_items = models.BooleanField(default=False)
    
    # Advanced configuration
    config = models.JSONField(default=dict, blank=True)
    
    # Triggering
    trigger_type = models.CharField(max_length=20, choices=TRIGGER_TYPE_CHOICES, default='manual')
    auto_apply = models.BooleanField(default=False)  # Apply automatically if conditions met
    
    # Timeline
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    
    # Usage limits
    usage_limit_total = models.IntegerField(null=True, blank=True)  # Total uses across all customers
    usage_limit_per_customer = models.IntegerField(null=True, blank=True)
    current_usage_count = models.IntegerField(default=0)
    
    # Display
    banner_image = models.ImageField(upload_to='campaigns/', blank=True)
    
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### Coupon

**Purpose**: Individual coupon codes generated from campaigns.

**Migrated from**: `freight/models/promotions.py`

```python
class Coupon(models.Model):
    """
    Individual coupon code.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='coupons')
    customer = models.ForeignKey('common.Customer', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Code
    code = models.CharField(max_length=50, unique=True)
    
    # Override campaign values (optional)
    custom_discount_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Usage
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    used_in_order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Expiry (can override campaign dates)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['workspace', 'customer']),
        ]
```

---

### DiscountRule

**Purpose**: Complex discount rules for tiered/conditional pricing.

```python
class DiscountRule(models.Model):
    """
    Complex discount rule (e.g., spend $100 get 10% off).
    """
    RULE_TYPE_CHOICES = (
        ('spend_amount', 'Spend Amount'),
        ('buy_quantity', 'Buy Quantity'),
        ('customer_tier', 'Customer Tier'),
        ('day_of_week', 'Day of Week'),
        ('time_of_day', 'Time of Day'),
    )
    
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='rules')
    
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES)
    
    # Conditions (stored as JSON for flexibility)
    conditions = models.JSONField(default=dict)
    # Example: {"min_amount": 100, "max_amount": 500}
    # Example: {"min_quantity": 3, "product_ids": [1, 2, 3]}
    
    # Action
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    discount_type = models.CharField(max_length=20, default='percentage')
    
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

---

### ReferralProgram

**Purpose**: Customer referral program configuration.

```python
class ReferralProgram(models.Model):
    """
    Referral program configuration.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    
    # Rewards
    referrer_reward_type = models.CharField(max_length=20, default='credit')  # 'credit', 'coupon', 'percentage'
    referrer_reward_value = models.DecimalField(max_digits=10, decimal_places=2)
    
    referee_reward_type = models.CharField(max_length=20, default='credit')
    referee_reward_value = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Conditions
    min_referee_purchase = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Limits
    max_referrals_per_customer = models.IntegerField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Referral

**Purpose**: Individual referral instances.

```python
class Referral(models.Model):
    """
    Individual referral instance.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('rewarded', 'Rewarded'),
        ('expired', 'Expired'),
    )
    
    program = models.ForeignKey(ReferralProgram, on_delete=models.CASCADE)
    
    referrer = models.ForeignKey('common.Customer', related_name='referrals_made', on_delete=models.CASCADE)
    referee = models.ForeignKey('common.Customer', related_name='referrals_received', on_delete=models.CASCADE)
    
    # Tracking
    referral_code = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Completion
    completed_at = models.DateTimeField(null=True, blank=True)
    qualifying_order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Rewards
    rewarded_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### Channel

**Purpose**: Marketing channel definition.

```python
class Channel(models.Model):
    """
    Marketing channel (e.g., Facebook, Instagram, Email, Affiliate).
    """
    CHANNEL_TYPE_CHOICES = (
        ('social', 'Social Media'),
        ('email', 'Email Marketing'),
        ('affiliate', 'Affiliate'),
        ('search', 'Search Engine'),
        ('direct', 'Direct'),
        ('referral', 'Referral'),
        ('other', 'Other'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    channel_type = models.CharField(max_length=20, choices=CHANNEL_TYPE_CHOICES)
    
    description = models.TextField(blank=True)
    icon = models.ImageField(upload_to='channels/', blank=True)
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### ChannelLink

**Purpose**: Trackable campaign links with UTM parameters.

```python
class ChannelLink(models.Model):
    """
    Trackable link for campaigns (with UTM parameters).
    """
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='links')
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)
    
    # Link details
    name = models.CharField(max_length=100)
    destination_url = models.URLField()
    
    # UTM parameters
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    utm_term = models.CharField(max_length=100, blank=True)
    utm_content = models.CharField(max_length=100, blank=True)
    
    # Short URL
    short_code = models.CharField(max_length=20, unique=True)
    short_url = models.URLField(blank=True)  # Auto-generated
    
    # Tracking
    click_count = models.IntegerField(default=0)
    conversion_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### LinkClick

**Purpose**: Track individual link clicks.

```python
class LinkClick(models.Model):
    """
    Individual link click tracking.
    """
    link = models.ForeignKey(ChannelLink, on_delete=models.CASCADE, related_name='clicks')
    
    # Visitor info
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    referrer = models.URLField(blank=True)
    
    # Geo
    country = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Conversion
    converted = models.BooleanField(default=False)
    order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    
    clicked_at = models.DateTimeField(auto_now_add=True)
```

---

### AffiliatePartner

**Purpose**: Affiliate partner management.

```python
class AffiliatePartner(models.Model):
    """
    Affiliate partner.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('terminated', 'Terminated'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.OneToOneField('common.Customer', on_delete=models.CASCADE)
    
    # Partner info
    company_name = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    
    # Tracking
    affiliate_code = models.CharField(max_length=50, unique=True)
    
    # Commission
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)  # Percentage
    commission_type = models.CharField(max_length=20, default='percentage')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Stats
    total_clicks = models.IntegerField(default=0)
    total_sales = models.IntegerField(default=0)
    total_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### CampaignAnalytics

**Purpose**: Aggregate campaign performance metrics.

```python
class CampaignAnalytics(models.Model):
    """
    Campaign analytics (daily aggregates).
    """
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='analytics')
    date = models.DateField()
    
    # Metrics
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    conversions = models.IntegerField(default=0)
    revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Coupons
    coupons_generated = models.IntegerField(default=0)
    coupons_used = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('campaign', 'date')
```

---

## API Endpoints

### Campaigns
- `GET /api/promo/campaigns/` - List active campaigns
- `GET /api/promo/campaigns/{code}/` - Get campaign details
- `POST /api/promo/campaigns/validate/` - Validate campaign eligibility

### Coupons
- `POST /api/promo/coupons/validate/` - Validate coupon code
- `POST /api/promo/coupons/apply/` - Apply coupon to cart
- `GET /api/promo/coupons/my/` - Get customer's coupons

### Referrals
- `GET /api/promo/referral/code/` - Get my referral code
- `POST /api/promo/referral/track/` - Track referral signup
- `GET /api/promo/referral/stats/` - Get referral statistics

### Affiliate
- `POST /api/promo/affiliate/apply/` - Apply for affiliate program
- `GET /api/promo/affiliate/dashboard/` - Get affiliate dashboard
- `GET /api/promo/affiliate/links/` - Get affiliate links

## Integration with Other Modules

- **bfg2_shop**: Apply coupons and discounts to orders
- **bfg2_finance**: Track commission payments to affiliates

# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.marketing module.
"""

from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db import IntegrityError
from .models import Coupon, Campaign, CampaignGroup, DiscountRule, ReferralProgram
from .models import GiftCard, CampaignDisplay


def clear_data():
    """Clear marketing module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order
    CampaignDisplay.objects.all().delete()
    GiftCard.objects.all().delete()
    Coupon.objects.all().delete()
    Campaign.objects.all().delete()
    DiscountRule.objects.all().delete()
    CampaignGroup.objects.all().delete()
    ReferralProgram.objects.all().delete()
    # 3. Invalidate caches (none for marketing)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed promo module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (admin_user, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating promo module data...'))
    
    admin_user = context.get('admin_user')
    
    # Create campaign group
    campaign_group = create_campaign_group(workspace, stdout, style)
    
    # Create campaigns
    campaigns = create_campaigns(workspace, campaign_group, admin_user, stdout, style)
    
    # Create discount rules
    discount_rules = create_discount_rules(workspace, stdout, style)
    
    # Create coupons
    coupons = create_coupons(workspace, campaigns, discount_rules, stdout, style)
    
    # Create gift cards
    gift_cards = create_gift_cards(workspace, context.get('customers', []), stdout, style)
    
    # Create referral programs
    referral_programs = create_referral_programs(workspace, stdout, style)

    # Create campaign displays (slides, category_entry, featured); use shop categories from context if present
    campaign_displays = create_campaign_displays(workspace, campaigns, stdout, style, **context)

    summary = [
        {'label': 'Campaigns', 'count': Campaign.objects.count()},
        {'label': 'Coupons', 'count': Coupon.objects.count()},
        {'label': 'Gift Cards', 'count': GiftCard.objects.count()},
    ]
    return {
        'campaign_group': campaign_group,
        'campaigns': campaigns,
        'discount_rules': discount_rules,
        'coupons': coupons,
        'gift_cards': gift_cards,
        'referral_programs': referral_programs,
        'campaign_displays': campaign_displays,
        'summary': summary,
    }


def create_campaign_group(workspace, stdout=None, style=None):
    """Create campaign group"""
    campaign_group, created = CampaignGroup.objects.get_or_create(
        workspace=workspace,
        name='Default Campaigns',
        defaults={
            'description': 'Default campaign group',
            'is_active': True,
        }
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created campaign group: {campaign_group.name}'))
    return campaign_group


def create_campaigns(workspace, campaign_group, admin_user, stdout=None, style=None):
    """Create campaigns"""
    campaigns_data = [
        {
            'name': 'Summer Sale',
            'campaign_type': 'email',
            'description': 'Summer promotion campaign',
            'start_date': timezone.now(),
            'end_date': timezone.now() + timedelta(days=30),
        },
        {
            'name': 'Holiday Special',
            'campaign_type': 'social',
            'description': 'Holiday season promotion',
            'start_date': timezone.now(),
            'end_date': timezone.now() + timedelta(days=60),
        },
    ]
    campaigns = []
    for camp_data in campaigns_data:
        campaign, created = Campaign.objects.get_or_create(
            workspace=workspace,
            name=camp_data['name'],
            defaults={
                'group': campaign_group,
                'campaign_type': camp_data['campaign_type'],
                'description': camp_data['description'],
                'start_date': camp_data['start_date'],
                'end_date': camp_data['end_date'],
                'is_active': True,
                'created_by': admin_user,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created campaign: {campaign.name}'))
        campaigns.append(campaign)
    return campaigns


def create_discount_rules(workspace, stdout=None, style=None):
    """Create discount rules"""
    discount_rules_data = [
        {
            'name': '10% Off',
            'discount_type': 'percentage',
            'discount_value': Decimal('10.00'),
            'apply_to': 'order',
        },
        {
            'name': '20% Off',
            'discount_type': 'percentage',
            'discount_value': Decimal('20.00'),
            'apply_to': 'order',
        },
    ]
    discount_rules = []
    for rule_data in discount_rules_data:
        discount_rule, created = DiscountRule.objects.get_or_create(
            workspace=workspace,
            name=rule_data['name'],
            defaults={
                'discount_type': rule_data['discount_type'],
                'discount_value': rule_data['discount_value'],
                'apply_to': rule_data['apply_to'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created discount rule: {discount_rule.name}'))
        discount_rules.append(discount_rule)
    return discount_rules


def create_coupons(workspace, campaigns, discount_rules, stdout=None, style=None):
    """Create coupons"""
    coupons_data = [
        {'code': 'WELCOME10', 'description': 'Welcome discount', 'discount_rule': discount_rules[0] if discount_rules else None},
        {'code': 'SAVE20', 'description': 'Save 20%', 'discount_rule': discount_rules[1] if len(discount_rules) > 1 else discount_rules[0] if discount_rules else None},
    ]
    coupons = []
    for coupon_data in coupons_data:
        if not coupon_data['discount_rule']:
            continue
        try:
            coupon, created = Coupon.objects.get_or_create(
                workspace=workspace,
                code=coupon_data['code'],
                defaults={
                    'campaign': campaigns[0] if campaigns else None,
                    'discount_rule': coupon_data['discount_rule'],
                    'description': coupon_data['description'],
                    'valid_from': timezone.now(),
                    'valid_until': timezone.now() + timedelta(days=365),
                    'is_active': True,
                }
            )
            if created and stdout:
                stdout.write(style.SUCCESS(f'✓ Created coupon: {coupon.code}'))
            coupons.append(coupon)
        except IntegrityError:
            pass
    return coupons


def create_gift_cards(workspace, customers, stdout=None, style=None):
    """Create gift cards"""
    from bfg.finance.models import Currency
    
    try:
        # Currency is global, not workspace-specific
        currency = Currency.objects.filter(code='USD', is_active=True).first()
        if not currency:
            currency = Currency.objects.filter(is_active=True).first()
        
        if not currency:
            if stdout:
                stdout.write(style.WARNING('⚠ Skipping gift cards - no currency found'))
            return []
        
        gift_cards_data = [
            {'initial_value': Decimal('50.00'), 'customer': customers[0] if customers else None},
            {'initial_value': Decimal('100.00'), 'customer': customers[1] if len(customers) > 1 else None},
            {'initial_value': Decimal('25.00'), 'customer': None},  # Generic gift card
        ]
        
        gift_cards = []
        for data in gift_cards_data:
            gift_card = GiftCard.objects.create(
                workspace=workspace,
                initial_value=data['initial_value'],
                balance=data['initial_value'],
                currency=currency,
                customer=data['customer'],
                is_active=True,
            )
            gift_cards.append(gift_card)
            if stdout:
                customer_info = f" for {data['customer'].user.username}" if data['customer'] else " (generic)"
                stdout.write(style.SUCCESS(f'✓ Created gift card: {gift_card.code}{customer_info}'))
        
        return gift_cards
    except Exception as e:
        if stdout:
            stdout.write(style.WARNING(f'⚠ Error creating gift cards: {str(e)}'))
        return []


def create_referral_programs(workspace, stdout=None, style=None):
    """Create referral programs"""
    referral_programs_data = [
        {
            'name': 'Standard Referral Program',
            'description': 'Standard referral program with fixed rewards',
            'referrer_reward': Decimal('10.00'),
            'referee_reward': Decimal('5.00'),
            'minimum_purchase': Decimal('50.00'),
        },
        {
            'name': 'Premium Referral Program',
            'description': 'Premium referral program with higher rewards',
            'referrer_reward': Decimal('25.00'),
            'referee_reward': Decimal('15.00'),
            'minimum_purchase': Decimal('100.00'),
        },
        {
            'name': 'No Minimum Referral',
            'description': 'Referral program with no minimum purchase requirement',
            'referrer_reward': Decimal('5.00'),
            'referee_reward': Decimal('5.00'),
            'minimum_purchase': None,
        },
    ]
    referral_programs = []
    for data in referral_programs_data:
        referral_program, created = ReferralProgram.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'description': data['description'],
                'referrer_reward': data['referrer_reward'],
                'referee_reward': data['referee_reward'],
                'minimum_purchase': data['minimum_purchase'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created referral program: {referral_program.name}'))
        referral_programs.append(referral_program)
    return referral_programs


def create_campaign_displays(workspace, campaigns, stdout=None, style=None, **context):
    """Create sample campaign displays: 3 slides, 8 category_entry, 3 featured (pickup).

    Images are read from {MEDIA_ROOT}/seed_images/store/ (same layout as shop seed_media):
    - Slides: slides/sample-1.webp, sample-2.webp, sample-3.webp
    - Category entry: categories/3-cp_categorylist.jpg … categories/14-cp_categorylist.jpg
    - Featured: featured/cms-banner1.webp, cms-banner2.webp, cms-banner3.webp

    Uses context['categories'] (from shop seed_data) when available so CampaignDisplay.rules
    get category_id; otherwise queries ProductCategory (requires shop to be seeded first).
    """
    import os
    from django.conf import settings
    from django.core.files import File

    seed_store = os.path.join(settings.MEDIA_ROOT, 'seed_images', 'store')

    def set_display_image(disp, relative_path, default_name='image'):
        """Set display.image from seed_images/store/{relative_path} if file exists."""
        src = os.path.join(seed_store, relative_path)
        if os.path.isfile(src):
            name = os.path.basename(relative_path)
            with open(src, 'rb') as f:
                disp.image.save(name, File(f), save=True)

    # Prefer categories from context (set by shop seed_data); fallback to ProductCategory query
    categories = list(context.get('categories', []))[:8] if context.get('categories') else []
    if not categories:
        try:
            from bfg.shop.models import ProductCategory
            categories = list(
                ProductCategory.objects.filter(workspace=workspace, parent__isnull=True)
                .order_by('order', 'name')[:8]
            )
        except Exception:
            categories = []

    campaign = campaigns[0] if campaigns else None
    displays = []

    # 3 slides – images from store/slides/
    slide_images = [
        'slides/sample-1.webp',
        'slides/sample-2.webp',
        'slides/sample-3.webp',
    ]
    slides_data = [
        {'order': 10, 'title': 'Welcome Sale', 'subtitle': 'Up to 30% off selected items', 'link_url': '/products'},
        {'order': 20, 'title': 'New Arrivals', 'subtitle': 'Discover the latest collection', 'link_url': '/products?new=1'},
        {'order': 30, 'title': 'Free Shipping', 'subtitle': 'On orders over $50', 'link_url': '/cart'},
    ]
    for i, data in enumerate(slides_data):
        disp = CampaignDisplay.objects.create(
            workspace=workspace,
            campaign=campaign,
            display_type='slide',
            order=data['order'],
            title=data['title'],
            subtitle=data['subtitle'],
            link_url=data.get('link_url', ''),
            is_active=True,
        )
        if i < len(slide_images):
            set_display_image(disp, slide_images[i])
        displays.append(disp)
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Created display: slide "{data["title"]}"'))

    # 8 category_entry – images from store/categories/
    category_img_rel = [
        'categories/3-cp_categorylist.jpg',
        'categories/6-cp_categorylist.jpg',
        'categories/9-cp_categorylist.jpg',
        'categories/10-cp_categorylist.jpg',
        'categories/11-cp_categorylist.jpg',
        'categories/12-cp_categorylist.jpg',
        'categories/13-cp_categorylist.jpg',
        'categories/14-cp_categorylist.jpg',
    ]
    for i in range(8):
        cat = categories[i] if i < len(categories) else None
        rules = [{'column': 'category_id', 'relation': 'equals', 'condition': str(cat.id)}] if cat else []
        disp = CampaignDisplay.objects.create(
            workspace=workspace,
            campaign=campaign,
            display_type='category_entry',
            order=100 + i,
            title=cat.name if cat else f'Category {i + 1}',
            link_url=f'/category/{getattr(cat, "slug", "")}' if cat else '',
            rules=rules,
            is_active=True,
        )
        if i < len(category_img_rel):
            set_display_image(disp, category_img_rel[i])
        displays.append(disp)
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Created display: category_entry "{disp.title}"'))

    # 3 featured (pickup) – images from store/featured/
    featured_img_rel = [
        'featured/cms-banner1.webp',
        'featured/cms-banner2.webp',
        'featured/cms-banner3.webp',
    ]
    featured_cats = categories[5:8] if len(categories) >= 6 else (categories[:3] if categories else [None, None, None])
    for i in range(3):
        cat = featured_cats[i] if i < len(featured_cats) and featured_cats[i] else None
        rules = [{'column': 'category_id', 'relation': 'equals', 'condition': str(cat.id)}] if cat else []
        disp = CampaignDisplay.objects.create(
            workspace=workspace,
            campaign=campaign,
            display_type='featured',
            order=200 + i,
            title=cat.name if cat else f'Featured {i + 1}',
            subtitle='Shop now' if cat else '',
            link_url=f'/category/{getattr(cat, "slug", "")}' if cat else '',
            rules=rules,
            is_active=True,
        )
        if i < len(featured_img_rel):
            set_display_image(disp, featured_img_rel[i])
        displays.append(disp)
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Created display: featured "{disp.title}"'))

    return displays


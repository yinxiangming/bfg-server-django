# -*- coding: utf-8 -*-
"""
Storefront promo API: GET /api/store/promo/?context=home
Returns types_present + available (slides, featured_categories, flash_sales, group_buys).
"""
from django.utils import timezone
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import NotFound

from bfg.marketing.models import Campaign, CampaignDisplay, CampaignParticipation, DiscountRule
from bfg.shop.models import Product, ProductCategory
from bfg.shop.schemas import apply_rules_to_product_queryset


def get_promo_available(workspace, request):
    """
    Build promo 'available' dict (slides, featured_categories, flash_sales, group_buys).
    Used by PromoView and by web page_service when rendering home page blocks with source='promo'.
    """
    now = timezone.now()
    campaigns_qs = Campaign.objects.filter(
        workspace=workspace,
        is_active=True,
        start_date__lte=now,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=now))
    campaign_ids = list(campaigns_qs.values_list('id', flat=True))

    displays = CampaignDisplay.objects.filter(
        is_active=True,
    ).filter(
        Q(campaign_id__in=campaign_ids) | Q(workspace=workspace, campaign__isnull=True)
    ).select_related('campaign', 'post').order_by('order')

    slides = []
    featured_categories = []
    for d in displays:
        if d.display_type == 'slide':
            img = getattr(d, 'image', None)
            slides.append({
                'id': d.id,
                'title': d.title or '',
                'subtitle': d.subtitle or '',
                'image': request.build_absolute_uri(img.url) if img else None,
                'link_url': d.link_url or '',
                'order': d.order,
            })
        elif d.display_type in ('category_entry', 'featured'):
            display_img = getattr(d, 'image', None)
            for cat in _resolve_categories_for_display(d, workspace):
                if d.display_type == 'featured':
                    img = display_img or getattr(cat, 'image', None)
                else:
                    img = getattr(cat, 'image', None) or display_img
                image_url = request.build_absolute_uri(img.url) if img else None
                featured_categories.append({
                    'id': d.id,
                    'display_type': d.display_type,
                    'title': d.title or '',
                    'image': image_url,
                    'category': {
                        'id': cat.id,
                        'name': cat.name,
                        'slug': getattr(cat, 'slug', ''),
                        'image': image_url,
                    },
                    'link_url': d.link_url or '',
                    'order': d.order,
                })

    flash_sales = []
    for dr in DiscountRule.objects.filter(
        workspace=workspace,
        is_active=True,
        valid_until__isnull=False,
        valid_until__gte=now,
    ).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=now)).prefetch_related('coupons'):
        coupon = dr.coupons.filter(campaign_id__in=campaign_ids).first()
        if not coupon:
            coupon = dr.coupons.filter(campaign__workspace=workspace).first()
        if coupon and (coupon.campaign_id in campaign_ids):
            flash_sales.append({
                'campaign_id': coupon.campaign_id,
                'discount_rule_id': dr.id,
                'display_label': dr.display_label or dr.name,
                'valid_until': dr.valid_until.isoformat() if dr.valid_until else None,
            })

    group_buys = []
    for c in campaigns_qs.filter(requires_participation=True, min_participants__isnull=False):
        current = CampaignParticipation.objects.filter(campaign=c).count()
        group_buys.append({
            'campaign_id': c.id,
            'min_participants': c.min_participants,
            'current_participants': current,
            'valid_until': c.end_date.isoformat() if c.end_date else None,
        })

    available = {}
    if slides:
        available['slides'] = slides
    if featured_categories:
        available['featured_categories'] = featured_categories
    if flash_sales:
        available['flash_sales'] = flash_sales
    if group_buys:
        available['group_buys'] = group_buys
    return available


def _resolve_categories_for_display(display, workspace, rule_match_type='all'):
    """Resolve ProductCategory list from display.rules using shared rule filter (same as ProductCategory)."""
    rules = display.rules or []
    if not rules:
        return []
    qs = Product.objects.filter(workspace=workspace).filter(categories__is_active=True)
    qs = apply_rules_to_product_queryset(qs, rules, rule_match_type=rule_match_type)
    category_ids = qs.values_list('categories__id', flat=True).distinct()
    category_ids = [x for x in category_ids if x is not None]
    if not category_ids:
        return []
    return list(ProductCategory.objects.filter(id__in=category_ids, workspace=workspace).order_by('order', 'name'))


class PromoView(APIView):
    """GET promo data for storefront (homepage)."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            raise NotFound("No workspace available.")
        context = request.query_params.get('context', 'home')
        available = get_promo_available(workspace, request)
        types_present = list(available.keys())
        return Response({
            'context': context,
            'available': available,
            'types_present': types_present,
        })

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CampaignViewSet,
    CampaignDisplayViewSet,
    CampaignParticipationViewSet,
    CouponViewSet,
    GiftCardViewSet,
    ReferralProgramViewSet,
    DiscountRuleViewSet,
    StampRecordViewSet,
)

router = DefaultRouter()
router.register(r'campaigns', CampaignViewSet, basename='campaign')
router.register(r'campaign-displays', CampaignDisplayViewSet, basename='campaign-display')
router.register(r'campaign-participations', CampaignParticipationViewSet, basename='campaign-participation')
router.register(r'stamp-records', StampRecordViewSet, basename='stamp-record')
router.register(r'coupons', CouponViewSet, basename='coupon')
router.register(r'gift-cards', GiftCardViewSet, basename='gift-card')
router.register(r'referral-programs', ReferralProgramViewSet, basename='referral-program')
router.register(r'discount-rules', DiscountRuleViewSet, basename='discount-rule')

urlpatterns = [
    path('', include(router.urls)),
]


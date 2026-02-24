"""
Storefront API URL Configuration

Customer-facing API routes prefixed with /api/store/
"""
from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import AllowAny
from .viewsets.storefront import (
    StorefrontProductViewSet,
    StorefrontCategoryViewSet,
    StorefrontCartViewSet,
    StorefrontOrderViewSet,
    StorefrontPaymentViewSet,
    StorefrontAddressViewSet,
)
from bfg.marketing.promo_views import PromoView

router = DefaultRouter()
router.register(r'products', StorefrontProductViewSet, basename='storefront-product')
router.register(r'categories', StorefrontCategoryViewSet, basename='storefront-category')
router.register(r'cart', StorefrontCartViewSet, basename='storefront-cart')
router.register(r'addresses', StorefrontAddressViewSet, basename='storefront-address')
router.register(r'orders', StorefrontOrderViewSet, basename='storefront-order')
router.register(r'payments', StorefrontPaymentViewSet, basename='storefront-payment')

urlpatterns = [
    # Custom payment callback route (must come before router.urls)
    # DRF router doesn't support regex in url_path, so we add it manually
    # Use AllowAny permission for callback endpoint
    # Support both with and without trailing slash for webhook compatibility
    re_path(r'^payments/callback/(?P<gateway>[^/.]+)/?$',
            StorefrontPaymentViewSet.as_view({'post': 'callback'}, permission_classes=[AllowAny]),
            name='storefront-payment-callback'),
    path('promo/', PromoView.as_view(), name='storefront-promo'),
    path('', include(router.urls)),
]


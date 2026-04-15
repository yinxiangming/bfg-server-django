"""
Test URL configuration
"""
from django.urls import path, include
from django.contrib import admin

from rest_framework_simplejwt.views import TokenObtainPairView
from config.serializers import CustomTokenObtainPairSerializer
from config.views import (
    register,
    forgot_password,
    reset_password_confirm,
    verify_email,
)

from django.views.generic import TemplateView

urlpatterns = [
    # allauth required route
    path('auth/account-confirm-email/<str:key>/', TemplateView.as_view(), name='account_confirm_email'),
    # BFG2 API v1 endpoints (matching main server structure)
    path('api/v1/', include([
        path('auth/', include([
            path('register/', register, name='register'),
            path('forgot-password/', forgot_password, name='forgot-password'),
            path('reset-password-confirm/', reset_password_confirm, name='reset-password-confirm'),
            path('verify-email/', verify_email, name='verify-email'),
            path('token/', TokenObtainPairView.as_view(serializer_class=CustomTokenObtainPairSerializer), name='token_obtain_pair'),
        ])),
        # Common module (workspaces, customers, addresses)
        path('', include('bfg.common.urls')),
        
        # Web/CMS module (sites, themes, languages, pages, posts, media, categories, tags, menus)
        path('web/', include('bfg.web.urls')),
        
        # Shop module (products, stores, orders, categories, variants, carts)
        path('shop/', include('bfg.shop.urls')),
        
        # Storefront API (customer-facing)
        path('store/', include('bfg.shop.urls_storefront')),
        
        # Delivery module (warehouses, carriers, manifests, consignments, packages)
        path('delivery/', include('bfg.delivery.urls')),
        
        # Marketing module (campaigns, coupons)
        path('marketing/', include('bfg.marketing.urls')),
        
        # Finance module
        path('finance/', include('bfg.finance.urls')),
        
        # Support module (tickets)
        path('support/', include('bfg.support.urls')),
        
        # Inbox module
        path('inbox/', include('bfg.inbox.urls')),

        # Platform module
        path('platform/', include('bfg.platform.urls')),
    ])),
]


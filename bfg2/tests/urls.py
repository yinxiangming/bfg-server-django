"""
Test URL configuration
"""
from django.urls import path, include
from django.contrib import admin

urlpatterns = [
    # Storefront API (customer-facing, no version prefix)
    path('api/store/', include('bfg.shop.urls_storefront')),
    
    # BFG2 API v1 endpoints (matching main server structure)
    path('api/v1/', include([
        # Common module (workspaces, customers, addresses)
        path('', include('bfg.common.urls')),
        
        # Web/CMS module (sites, themes, languages, pages, posts, media, categories, tags, menus)
        path('web/', include('bfg.web.urls')),
        
        # Shop module (products, stores, orders, categories, variants, carts)
        path('shop/', include('bfg.shop.urls')),
        
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
    ])),
]


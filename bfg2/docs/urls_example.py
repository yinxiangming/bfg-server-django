# BFG2 URL Configuration Example
#
# This is a reference urls.py for projects using the BFG2 library

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    # =============================================================================
    # ADMIN
    # =============================================================================
    path('admin/', admin.site.urls),
    
    # =============================================================================
    # AUTHENTICATION (JWT)
    # =============================================================================
    path('api/auth/', include([
        path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
        path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
        path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    ])),
    
    # =============================================================================
    # API DOCUMENTATION
    # =============================================================================
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # =============================================================================
    # BFG2 API v1
    # =============================================================================
    path('api/v1/', include([
        # Common module
        path('workspaces/', include('bfg.common.urls.workspace_urls')),
        path('customers/', include('bfg.common.urls.customer_urls')),
        path('addresses/', include('bfg.common.urls.address_urls')),
        path('settings/', include('bfg.common.urls.settings_urls')),
        
        # Web/CMS module
        path('sites/', include('bfg.web.urls.site_urls')),
        path('pages/', include('bfg.web.urls.page_urls')),
        path('posts/', include('bfg.web.urls.post_urls')),
        path('media/', include('bfg.web.urls.media_urls')),
        path('categories/', include('bfg.web.urls.category_urls')),
        path('tags/', include('bfg.web.urls.tag_urls')),
        
        # Shop module
        path('products/', include('bfg.shop.urls.product_urls')),
        path('cart/', include('bfg.shop.urls.cart_urls')),
        path('orders/', include('bfg.shop.urls.order_urls')),
        path('reviews/', include('bfg.shop.urls.review_urls')),
        path('stores/', include('bfg.shop.urls.store_urls')),
        
        # Delivery module
        path('warehouses/', include('bfg.delivery.urls.warehouse_urls')),
        path('carriers/', include('bfg.delivery.urls.carrier_urls')),
        path('manifests/', include('bfg.delivery.urls.manifest_urls')),
        path('consignments/', include('bfg.delivery.urls.consignment_urls')),
        path('packages/', include('bfg.delivery.urls.package_urls')),
        
        # Finance module (when implemented)
        # path('payments/', include('bfg.finance.urls.payment_urls')),
        # path('invoices/', include('bfg.finance.urls.invoice_urls')),
        
        # Promo module (when implemented)
        # path('coupons/', include('bfg.marketing.urls.coupon_urls')),
        # path('campaigns/', include('bfg.marketing.urls.campaign_urls')),
    ])),
]

# Serve static/media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

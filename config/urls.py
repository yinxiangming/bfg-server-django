"""
BFG Framework URL Configuration (core only; no apps.* routes).
"""
import os
from django.urls import re_path, include, path
from config.local_apps import get_local_apps
from django.contrib import admin
from django.conf.urls.static import static
from django.conf import settings
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from config.serializers import CustomTokenObtainPairSerializer
from config.views import register, forgot_password, reset_password_confirm, verify_email, provision_user
from config.social_auth import (
    social_login_view,
    social_callback_view,
    social_callback_view_csrf_exempt,
)

urlpatterns = [
    re_path(r'^admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/v1/', include([
        path('agent/', include('bfg.core.agent_urls')),
        path('internal/auth/provision-user/', provision_user, name='provision_user'),
        path('auth/', include([
            path('register/', register, name='register'),
            path('forgot-password/', forgot_password, name='forgot-password'),
            path('reset-password-confirm/', reset_password_confirm, name='reset-password-confirm'),
            path('verify-email/', verify_email, name='verify-email'),
            path('token/', TokenObtainPairView.as_view(serializer_class=CustomTokenObtainPairSerializer), name='token_obtain_pair'),
            path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
            path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),             
            path('google/login/', social_login_view, {'provider': 'google'}, name='google_login'),
            path('google/callback/', social_callback_view, {'provider': 'google'}, name='google_callback'),
            path('facebook/login/', social_login_view, {'provider': 'facebook'}, name='facebook_login'),
            path('facebook/callback/', social_callback_view, {'provider': 'facebook'}, name='facebook_callback'),
            path('apple/login/', social_login_view, {'provider': 'apple'}, name='apple_login'),
            path('apple/callback/', social_callback_view_csrf_exempt, {'provider': 'apple'}, name='apple_callback'),
        ])),
        path('', include('bfg.common.urls')),
        path('web/', include('bfg.web.urls')),
        path('', include('bfg.shop.urls')),
        path('', include('bfg.delivery.urls')),
        path('', include('bfg.marketing.urls')),
        path('support/', include('bfg.support.urls')),
        path('inbox/', include('bfg.inbox.urls')),
        path('', include('bfg.finance.urls')),
        path('store/', include('bfg.shop.urls_storefront')),
        *[path(f'{app}/', include(f'apps.{app}.urls')) for app in get_local_apps()],
    ])),
]

# static() only adds /media/ when DEBUG=True; production needs explicit routes or nginx alias.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + static(
        '/images/', document_root=os.path.join(settings.MEDIA_ROOT, 'images')
    )
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(
            r'^images/(?P<path>.*)$',
            serve,
            {'document_root': os.path.join(settings.MEDIA_ROOT, 'images')},
        ),
    ]

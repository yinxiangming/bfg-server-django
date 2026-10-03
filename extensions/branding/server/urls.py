from django.urls import path

from .console_views import BrandPortalConsoleView
from .views import (
    PortalConfigView,
    PortalFinalizeView,
    PortalLoginView,
    PortalMenuView,
    PortalPageView,
    PortalPostView,
    PortalRegisterView,
    PortalSSOStartView,
    PortalVerifyEmailView,
)


app_name = 'brand_portal'

urlpatterns = [
    path(
        'v1/console/workspaces/<int:workspace_id>/',
        BrandPortalConsoleView.as_view(),
        name='v1-console-workspace',
    ),
    path('v1/config/', PortalConfigView.as_view(), name='v1-config'),
    path('v1/auth/register/', PortalRegisterView.as_view(), name='v1-register'),
    path('v1/auth/verify-email/', PortalVerifyEmailView.as_view(), name='v1-verify-email'),
    path('v1/auth/login/', PortalLoginView.as_view(), name='v1-login'),
    path('v1/auth/sso/start/', PortalSSOStartView.as_view(), name='v1-sso-start'),
    path('v1/auth/finalize/', PortalFinalizeView.as_view(), name='v1-finalize'),
    path('v1/cms/pages/<slug:slug>/', PortalPageView.as_view(), name='v1-page'),
    path('v1/cms/posts/<slug:slug>/', PortalPostView.as_view(), name='v1-post'),
    path('v1/cms/menus/<slug:slug>/', PortalMenuView.as_view(), name='v1-menu'),
]

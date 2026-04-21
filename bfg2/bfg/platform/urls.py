# -*- coding: utf-8 -*-
"""
Platform URL configuration.

Mounted in the host project as:
  path('api/v1/', include([..., path('platform/', include('bfg.platform.urls')), ...]))
See resale-website/server/config/urls.py.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from bfg.platform.views.workspace_views import WorkspaceViewSet, PlanViewSet, SSOConfigViewSet
from bfg.platform.views.auth_views import AuthViewSet, InternalAuthViewSet
from bfg.platform.views.subscription_views import WebhookViewSet

router = DefaultRouter()
router.register(r'workspaces', WorkspaceViewSet, basename='platform-workspace')
router.register(r'plans',      PlanViewSet,      basename='platform-plan')
router.register(r'sso',        SSOConfigViewSet, basename='platform-sso')
router.register(r'auth',       AuthViewSet,      basename='platform-auth')
router.register(r'internal',   InternalAuthViewSet, basename='platform-internal')
router.register(r'webhooks',   WebhookViewSet,   basename='platform-webhook')

urlpatterns = [
    path('', include(router.urls)),
]

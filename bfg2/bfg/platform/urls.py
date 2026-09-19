# -*- coding: utf-8 -*-
"""
Platform URL configuration.

Mounted in the host project as:
  path('api/v1/', include([..., path('platform/', include('bfg.platform.urls')), ...]))
See the host project's config/urls.py.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from bfg.platform.views.workspace_views import WorkspaceViewSet, PlanViewSet, SSOConfigViewSet
from bfg.platform.views.auth_views import AuthViewSet, InternalAuthViewSet
from bfg.platform.views.switch_workspace_view import switch_workspace
from bfg.platform.views.console_views import ConsoleWorkspaceViewSet
from bfg.platform.views.console_admin_views import (
    ConsoleExchangeRateViewSet,
    ConsoleMeterPriceViewSet,
    ConsolePlatformVariableViewSet,
    ConsoleWorkspaceAdminViewSet,
)
from bfg.platform.views.control_views import (
    PlatformControlAuditEventViewSet,
    PlatformControlClusterViewSet,
    PlatformControlExchangeRateViewSet,
    PlatformControlMeterPriceViewSet,
    PlatformControlStatusViewSet,
    PlatformControlVariableViewSet,
    PlatformControlWorkspaceViewSet,
)

router = DefaultRouter()
router.register(r'workspaces', WorkspaceViewSet, basename='platform-workspace')
router.register(r'plans',      PlanViewSet,      basename='platform-plan')
router.register(r'sso',        SSOConfigViewSet, basename='platform-sso')
router.register(r'auth',       AuthViewSet,      basename='platform-auth')
router.register(r'internal',   InternalAuthViewSet, basename='platform-internal')
# What a platform administrator alone may do to a workspace shares the console's
# own ``workspaces`` prefix, so that it reads as part of the same resource. It is
# registered first on purpose: it declares no list route, and the router's api
# root takes the last basename registered under a prefix, which has to be the one
# that has a list to link to. The two never shadow each other's URLs — every path
# below carries a suffix of its own.
router.register(r'console/workspaces', ConsoleWorkspaceAdminViewSet, basename='platform-console-workspace-admin')
router.register(r'console/workspaces', ConsoleWorkspaceViewSet, basename='platform-console-workspace')
router.register(r'console/variables', ConsolePlatformVariableViewSet, basename='platform-console-variable')
router.register(r'console/meter-prices', ConsoleMeterPriceViewSet, basename='platform-console-meter-price')
router.register(r'console/exchange-rates', ConsoleExchangeRateViewSet, basename='platform-console-exchange-rate')
# The owner console stays under ``console/``. Deployment lifecycle, Cluster and
# audit controls are a separate superuser-only contract under ``control/``.
router.register(r'control/workspaces', PlatformControlWorkspaceViewSet, basename='platform-control-workspace')
router.register(r'control/status', PlatformControlStatusViewSet, basename='platform-control-status')
router.register(r'control/clusters', PlatformControlClusterViewSet, basename='platform-control-cluster')
router.register(r'control/audit-events', PlatformControlAuditEventViewSet, basename='platform-control-audit-event')
# Existing configuration resources are strict-superuser views. Publish their
# control-plane aliases before clients migrate off the historical console path.
router.register(r'control/variables', PlatformControlVariableViewSet, basename='platform-control-variable')
router.register(r'control/meter-prices', PlatformControlMeterPriceViewSet, basename='platform-control-meter-price')
router.register(r'control/exchange-rates', PlatformControlExchangeRateViewSet, basename='platform-control-exchange-rate')

urlpatterns = [
    path('', include(router.urls)),
    path('switch-workspace/', switch_workspace, name='platform-switch-workspace'),
]

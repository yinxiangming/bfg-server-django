# -*- coding: utf-8 -*-
from bfg.platform.views.workspace_views import WorkspaceViewSet, PlanViewSet, SSOConfigViewSet
from bfg.platform.views.auth_views import AuthViewSet, InternalAuthViewSet
from bfg.platform.views.subscription_views import WebhookViewSet
from bfg.platform.views.console_views import ConsoleWorkspaceViewSet

__all__ = [
    'WorkspaceViewSet',
    'PlanViewSet',
    'SSOConfigViewSet',
    'AuthViewSet',
    'InternalAuthViewSet',
    'WebhookViewSet',
    'ConsoleWorkspaceViewSet',
]

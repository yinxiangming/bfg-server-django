# -*- coding: utf-8 -*-
"""
Agent API URL routes. Mount at api/v1/agent/ in config/urls.py.
"""
from django.urls import path
from .agent_views import AgentCapabilitiesView, AgentExecuteView, AgentChatView

urlpatterns = [
    path("capabilities/", AgentCapabilitiesView.as_view(), name="agent-capabilities"),
    path("execute/", AgentExecuteView.as_view(), name="agent-execute"),
    path("chat/", AgentChatView.as_view(), name="agent-chat"),
]

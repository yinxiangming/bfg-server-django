# -*- coding: utf-8 -*-
from django.urls import path

from __APP_MODULE__.views import OpenAIAnalyzeView

urlpatterns = [
    path('ai/analyze/', OpenAIAnalyzeView.as_view(), name='__APP_SLUG__-ai-analyze'),
]

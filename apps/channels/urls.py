# -*- coding: utf-8 -*-
from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.channels.views import (
    ChannelFAQRuleViewSet,
    ExternalChannelViewSet,
    ExternalFeedbackViewSet,
    ExternalListingViewSet,
    ExternalQuestionViewSet,
    OpenAIAnalyzeView,
)

router = DefaultRouter()
router.register("channels", ExternalChannelViewSet, basename="channel")
router.register("listings", ExternalListingViewSet, basename="listing")
router.register("feedback", ExternalFeedbackViewSet, basename="feedback")
router.register("questions", ExternalQuestionViewSet, basename="question")
router.register("faq-rules", ChannelFAQRuleViewSet, basename="faq-rule")

urlpatterns = router.urls + [
    path("ai/analyze/", OpenAIAnalyzeView.as_view(), name="channels-ai-analyze"),
]

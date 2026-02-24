from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    MessageViewSet, MessageTemplateViewSet,
    MessageRecipientViewSet, SMSMessageViewSet
)

router = DefaultRouter()
router.register(r'messages', MessageViewSet, basename='message')
router.register(r'templates', MessageTemplateViewSet, basename='template')
router.register(r'recipients', MessageRecipientViewSet, basename='recipient')
router.register(r'sms', SMSMessageViewSet, basename='sms')

urlpatterns = [
    path('', include(router.urls)),
]

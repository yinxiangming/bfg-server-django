from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SupportTicketViewSet,
    SupportOptionsView,
    TicketCategoryViewSet,
    TicketPriorityViewSet,
)

router = DefaultRouter()
router.register(r'tickets', SupportTicketViewSet, basename='ticket')
router.register(r'ticket-categories', TicketCategoryViewSet, basename='ticket-category')
router.register(r'ticket-priorities', TicketPriorityViewSet, basename='ticket-priority')

urlpatterns = [
    path('options/', SupportOptionsView.as_view()),
    path('', include(router.urls)),
]


from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SiteViewSet, ThemeViewSet, LanguageViewSet, PageViewSet, PostViewSet,
    MediaViewSet, CategoryViewSet, TagViewSet, MenuViewSet, InquiryViewSet,
    BookingTimeSlotViewSet, BookingViewSet,
    BlockTypesView, BlockValidateView,
    NewsletterSubscriptionViewSet, NewsletterUnsubscribeByTokenView,
    NewsletterTemplateViewSet, NewsletterSendViewSet, NewsletterSendLogViewSet,
)

router = DefaultRouter()
router.register(r'sites', SiteViewSet, basename='site')
router.register(r'themes', ThemeViewSet, basename='theme')
router.register(r'languages', LanguageViewSet, basename='language')
router.register(r'pages', PageViewSet, basename='page')
router.register(r'posts', PostViewSet, basename='post')
router.register(r'media', MediaViewSet, basename='media')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'tags', TagViewSet, basename='tag')
router.register(r'menus', MenuViewSet, basename='menu')
router.register(r'inquiries', InquiryViewSet, basename='inquiry')
router.register(r'timeslots', BookingTimeSlotViewSet, basename='booking-timeslot')
router.register(r'bookings', BookingViewSet, basename='booking')
router.register(r'newsletter-subscriptions', NewsletterSubscriptionViewSet, basename='newsletter-subscription')
router.register(r'newsletter-templates', NewsletterTemplateViewSet, basename='newsletter-template')
router.register(r'newsletter-sends', NewsletterSendViewSet, basename='newsletter-send')
router.register(r'newsletter-send-logs', NewsletterSendLogViewSet, basename='newsletter-send-log')

urlpatterns = [
    path('', include(router.urls)),
    path('blocks/types/', BlockTypesView.as_view(), name='block-types'),
    path('blocks/validate/', BlockValidateView.as_view(), name='block-validate'),
    path('newsletter/unsubscribe/', NewsletterUnsubscribeByTokenView.as_view(), name='newsletter-unsubscribe'),
]

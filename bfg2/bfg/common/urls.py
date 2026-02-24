from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    WorkspaceViewSet, CustomerViewSet, AddressViewSet, SettingsViewSet,
    EmailConfigViewSet,
    UserViewSet, OptionsView,
    CustomerSegmentViewSet, CustomerTagViewSet,
    StaffRoleViewSet,
    MeViewSet, MeAddressViewSet, MeSettingsViewSet, MeOrdersViewSet,
    MePaymentMethodViewSet, MePaymentViewSet, MeInvoiceViewSet,
    countries_list
)

router = DefaultRouter()
router.register(r'workspaces', WorkspaceViewSet, basename='workspace')
router.register(r'customers', CustomerViewSet, basename='customer')
router.register(r'addresses', AddressViewSet, basename='address')
router.register(r'settings', SettingsViewSet, basename='settings')
router.register(r'email-configs', EmailConfigViewSet, basename='email-config')
router.register(r'users', UserViewSet, basename='user')
# New model ViewSets
router.register(r'customer-segments', CustomerSegmentViewSet, basename='customer-segment')
router.register(r'customer-tags', CustomerTagViewSet, basename='customer-tag')
router.register(r'staff-roles', StaffRoleViewSet, basename='staff-role')
# Me API - unified personal information API
# Note: me/ and me/settings/ are registered as direct paths, not via router to avoid conflicts
router.register(r'me/addresses', MeAddressViewSet, basename='me-address')
router.register(r'me/orders', MeOrdersViewSet, basename='me-orders')
router.register(r'me/payment-methods', MePaymentMethodViewSet, basename='me-payment-method')
router.register(r'me/payments', MePaymentViewSet, basename='me-payment')
router.register(r'me/invoices', MeInvoiceViewSet, basename='me-invoice')

urlpatterns = [
    # Me API - specific action routes must come before router.urls
    path('me/change-password/', MeViewSet.as_view({'post': 'change_password'}), name='me-change-password'),
    path('me/reset-password/', MeViewSet.as_view({'post': 'reset_password'}), name='me-reset-password'),
    path('me/avatar/', MeViewSet.as_view({'post': 'avatar_upload'}), name='me-avatar'),
    # Me API singleton endpoints (must come before router to avoid conflicts)
    path('me/settings/', MeSettingsViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='me-settings-detail'),
    path('me/', MeViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='me-detail'),
    # Router URLs (includes me/addresses/, me/orders/)
    path('', include(router.urls)),
    path('options/', OptionsView.as_view(), name='options'),
    path('countries/', countries_list, name='countries-list'),
]

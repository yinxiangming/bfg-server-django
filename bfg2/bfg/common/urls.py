from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    WorkspaceViewSet, CustomerViewSet, AddressViewSet, SettingsViewSet,
    EmailConfigViewSet,
    SocialAuthConfigViewSet,
    UserViewSet, OptionsView,
    CustomerSegmentViewSet, CustomerTagViewSet,
    StaffRoleViewSet, StaffMemberViewSet,
    InvitationViewSet, InvitationPreviewView, InvitationAcceptView,
    MeViewSet, MeAddressViewSet, MeSettingsViewSet, MeOrdersViewSet,
    MeDashboardStatsView,
    MePaymentMethodViewSet, MePaymentViewSet, MeInvoiceViewSet,
    MeWalletViewSet, MeWithdrawalRequestViewSet,
    MeSupportOptionsView, MeTicketsViewSet,
    APIKeyViewSet,
    countries_list
)

router = DefaultRouter()
router.register(r'workspaces', WorkspaceViewSet, basename='workspace')
router.register(r'customers', CustomerViewSet, basename='customer')
router.register(r'addresses', AddressViewSet, basename='address')
router.register(r'settings', SettingsViewSet, basename='settings')
router.register(r'email-configs', EmailConfigViewSet, basename='email-config')
router.register(r'social-auth-configs', SocialAuthConfigViewSet, basename='social-auth-config')
router.register(r'users', UserViewSet, basename='user')
# New model ViewSets
router.register(r'customer-segments', CustomerSegmentViewSet, basename='customer-segment')
router.register(r'customer-tags', CustomerTagViewSet, basename='customer-tag')
router.register(r'staff-roles', StaffRoleViewSet, basename='staff-role')
router.register(r'staff-members', StaffMemberViewSet, basename='staff-member')
router.register(r'staff-invitations', InvitationViewSet, basename='staff-invitation')
router.register(r'api-keys', APIKeyViewSet, basename='api-key')
# Me API - unified personal information API
# Note: me/ and me/settings/ are registered as direct paths, not via router to avoid conflicts
router.register(r'me/addresses', MeAddressViewSet, basename='me-address')
router.register(r'me/orders', MeOrdersViewSet, basename='me-orders')
router.register(r'me/payment-methods', MePaymentMethodViewSet, basename='me-payment-method')
router.register(r'me/payments', MePaymentViewSet, basename='me-payment')
router.register(r'me/invoices', MeInvoiceViewSet, basename='me-invoice')
router.register(r'me/wallets', MeWalletViewSet, basename='me-wallet')
router.register(r'me/withdrawal-requests', MeWithdrawalRequestViewSet, basename='me-withdrawal-request')
router.register(r'me/tickets', MeTicketsViewSet, basename='me-tickets')

urlpatterns = [
    # Public invitation endpoints (no workspace context required) — must come before router
    path('invitations/preview/', InvitationPreviewView.as_view(), name='invitation-preview'),
    path('invitations/accept/', InvitationAcceptView.as_view(), name='invitation-accept'),
    # Me API - specific action routes must come before router.urls
    path('me/dashboard-stats/', MeDashboardStatsView.as_view(), name='me-dashboard-stats'),
    path('me/support-options/', MeSupportOptionsView.as_view(), name='me-support-options'),
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

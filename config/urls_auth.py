from django.urls import path, include

urlpatterns = [
    # Map dj-rest-auth exactly as main urls.py does
    path('', include('dj_rest_auth.urls')),
    path('registration/', include('dj_rest_auth.registration.urls')),
    # Provide the target for allauth account_confirm_email reverse
    from django.views.generic import TemplateView
    path('account-confirm-email/<str:key>/', TemplateView.as_view(), name='account_confirm_email'),
]

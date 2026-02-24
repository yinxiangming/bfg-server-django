from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    InvoiceViewSet, PaymentViewSet, PaymentMethodViewSet,
    PaymentGatewayViewSet, CurrencyViewSet, BrandViewSet, FinancialCodeViewSet,
    TaxRateViewSet
)

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'payment-methods', PaymentMethodViewSet, basename='payment-method')
router.register(r'payment-gateways', PaymentGatewayViewSet, basename='payment-gateway')
router.register(r'currencies', CurrencyViewSet, basename='currency')
router.register(r'brands', BrandViewSet, basename='brand')
router.register(r'financial-codes', FinancialCodeViewSet, basename='financial-code')
router.register(r'tax-rates', TaxRateViewSet, basename='tax-rate')

urlpatterns = [
    path('', include(router.urls)),
]

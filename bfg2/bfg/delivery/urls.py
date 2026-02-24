from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    WarehouseViewSet,
    ConsignmentViewSet,
    CarrierViewSet,
    FreightServiceViewSet,
    PackagingTypeViewSet,
    FreightStatusViewSet,
    TrackingEventViewSet,
    DeliveryZoneViewSet,
    PackageViewSet,
    PackageTemplateViewSet,
)

router = DefaultRouter()
router.register(r'warehouses', WarehouseViewSet, basename='warehouse')
router.register(r'consignments', ConsignmentViewSet, basename='consignment')
router.register(r'carriers', CarrierViewSet, basename='carrier')
router.register(r'freight-services', FreightServiceViewSet, basename='freight-service')
router.register(r'packaging-types', PackagingTypeViewSet, basename='packaging-type')
router.register(r'freight-statuses', FreightStatusViewSet, basename='freight-status')
router.register(r'tracking-events', TrackingEventViewSet, basename='tracking-event')
router.register(r'delivery-zones', DeliveryZoneViewSet, basename='delivery-zone')
router.register(r'packages', PackageViewSet, basename='package')
router.register(r'package-templates', PackageTemplateViewSet, basename='package-template')

urlpatterns = [
    path('', include(router.urls)),
]

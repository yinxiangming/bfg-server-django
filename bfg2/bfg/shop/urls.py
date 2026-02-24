from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .viewsets import (
    ProductViewSet, ProductCategoryViewSet as CategoryViewSet, ProductTagViewSet,
    ProductVariantViewSet, StoreViewSet, CartViewSet, OrderViewSet,
    MediaViewSet, ProductMediaViewSet, SalesChannelViewSet, ProductChannelListingViewSet,
    ChannelCollectionViewSet, ReturnViewSet, ReturnLineItemViewSet,
    ProductReviewViewSet, SubscriptionPlanViewSet, OrderPackageViewSet
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'variants', ProductVariantViewSet, basename='variant')
router.register(r'stores', StoreViewSet, basename='store')
router.register(r'carts', CartViewSet, basename='cart')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'reviews', ProductReviewViewSet, basename='review')
router.register(r'media', MediaViewSet, basename='media')
router.register(r'product-media', ProductMediaViewSet, basename='product-media')
router.register(r'sales-channels', SalesChannelViewSet, basename='sales-channel')
router.register(r'subscription-plans', SubscriptionPlanViewSet, basename='subscription-plan')
router.register(r'channel-listings', ProductChannelListingViewSet, basename='channel-listing')
router.register(r'collections', ChannelCollectionViewSet, basename='collection')
router.register(r'returns', ReturnViewSet, basename='return')
router.register(r'return-items', ReturnLineItemViewSet, basename='return-item')
router.register(r'order-packages', OrderPackageViewSet, basename='order-package')

# Custom nested routes must come BEFORE router.urls to be matched first
urlpatterns = [
    # Nested route for products/categories (must be before router.urls)
    path('products/categories/', CategoryViewSet.as_view({'get': 'list', 'post': 'create'}), name='product-category-list'),
    path('products/categories/<int:pk>/', CategoryViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='product-category-detail'),
    # Nested route for products/tags (must be before router.urls)
    path('products/tags/', ProductTagViewSet.as_view({'get': 'list', 'post': 'create'}), name='product-tag-list'),
    path('products/tags/<int:pk>/', ProductTagViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='product-tag-detail'),
    # Router URLs (includes products/, categories/, etc.)
    path('', include(router.urls)),
]

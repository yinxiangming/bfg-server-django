"""
BFG Shop Module API Views

This file is kept for backward compatibility.
All ViewSets have been moved to viewsets/ directory.
"""

# Import all ViewSets from viewsets module for backward compatibility
from .viewsets import (
    ProductCategoryViewSet,
    ProductTagViewSet,
    ProductViewSet,
    ProductVariantViewSet,
    ProductReviewViewSet,
    MediaViewSet,
    ProductMediaViewSet,
    CartViewSet,
    OrderViewSet,
    SalesChannelViewSet,
    ProductChannelListingViewSet,
    ChannelCollectionViewSet,
    ReturnViewSet,
    ReturnLineItemViewSet,
    StoreViewSet,
)

__all__ = [
    'ProductCategoryViewSet',
    'ProductTagViewSet',
    'ProductViewSet',
    'ProductVariantViewSet',
    'ProductReviewViewSet',
    'MediaViewSet',
    'ProductMediaViewSet',
    'CartViewSet',
    'OrderViewSet',
    'SalesChannelViewSet',
    'ProductChannelListingViewSet',
    'ChannelCollectionViewSet',
    'ReturnViewSet',
    'ReturnLineItemViewSet',
    'StoreViewSet',
]

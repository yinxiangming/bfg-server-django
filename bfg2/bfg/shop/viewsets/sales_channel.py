"""
Sales Channel ViewSets
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff
from bfg.shop.models import SalesChannel, ProductChannelListing, ChannelCollection, Product
from bfg.shop.serializers import (
    SalesChannelSerializer, ProductChannelListingSerializer, ChannelCollectionSerializer
)


class SalesChannelViewSet(viewsets.ModelViewSet):
    """Sales channel management ViewSet"""
    serializer_class = SalesChannelSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        """Get sales channels for current workspace"""
        return SalesChannel.objects.filter(
            workspace=self.request.workspace
        ).prefetch_related('product_listings', 'collection_listings')
    
    def perform_create(self, serializer):
        """Create sales channel with workspace"""
        serializer.save(workspace=self.request.workspace)
    
    @action(detail=True, methods=['post'])
    def add_product(self, request, pk=None):
        """Add product to channel"""
        channel = self.get_object()
        product_id = request.data.get('product_id')
        
        if not product_id:
            return Response(
                {'detail': 'product_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            product = Product.objects.get(
                id=product_id,
                workspace=request.workspace
            )
            
            listing, created = ProductChannelListing.objects.get_or_create(
                channel=channel,
                product=product
            )
            
            return Response({
                'success': True,
                'created': created,
                'product_id': product.id,
                'product_name': product.name
            })
        except Product.DoesNotExist:
            return Response(
                {'detail': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    def remove_product(self, request, pk=None):
        """Remove product from channel"""
        channel = self.get_object()
        product_id = request.data.get('product_id')
        
        if not product_id:
            return Response(
                {'detail': 'product_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            listing = ProductChannelListing.objects.get(
                channel=channel,
                product_id=product_id
            )
            listing.delete()
            return Response({'success': True})
        except ProductChannelListing.DoesNotExist:
            return Response(
                {'detail': 'Product not in this channel'},
                status=status.HTTP_404_NOT_FOUND
            )


class ProductChannelListingViewSet(viewsets.ModelViewSet):
    """Product channel listing management ViewSet"""
    serializer_class = ProductChannelListingSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get product channel listings"""
        queryset = ProductChannelListing.objects.filter(
            channel__workspace=self.request.workspace
        ).select_related('product', 'channel')
        
        channel_id = self.request.query_params.get('channel')
        if channel_id:
            queryset = queryset.filter(channel_id=channel_id)
        
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        return queryset


class ChannelCollectionViewSet(viewsets.ModelViewSet):
    """Channel collection management ViewSet"""
    serializer_class = ChannelCollectionSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get channel collections"""
        queryset = ChannelCollection.objects.filter(
            channel__workspace=self.request.workspace
        ).select_related('category', 'channel')
        
        channel_id = self.request.query_params.get('channel')
        if channel_id:
            queryset = queryset.filter(channel_id=channel_id)
        
        return queryset


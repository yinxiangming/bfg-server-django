# -*- coding: utf-8 -*-
"""
Wishlist ViewSets: admin (list/filter/delete) and storefront (add/remove/list mine).
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, NotFound

from bfg.core.permissions import IsWorkspaceStaff
from bfg.common.models import Customer
from bfg.common.utils import get_required_workspace
from bfg.shop.models import Wishlist, Product
from bfg.shop._serializers import WishlistSerializer


class WishlistViewSet(viewsets.ModelViewSet):
    """Admin wishlist ViewSet: list, filter by customer/product, delete only."""
    serializer_class = WishlistSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    http_method_names = ['get', 'delete', 'head', 'options']

    def get_queryset(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            raise NotFound("No workspace available.")
        qs = Wishlist.objects.filter(workspace=workspace).select_related(
            'customer', 'customer__user', 'product'
        ).order_by('-created_at')
        customer_id = self.request.query_params.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        product_id = self.request.query_params.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs


class StorefrontWishlistViewSet(viewsets.GenericViewSet):
    """Storefront wishlist: list mine, add product, remove product."""
    permission_classes = [IsAuthenticated]

    def _get_customer(self, request):
        workspace = get_required_workspace(request)
        customer = Customer.objects.filter(
            workspace=workspace,
            user=request.user
        ).first()
        if not customer:
            raise NotFound("Customer profile not found.")
        return workspace, customer

    def list(self, request):
        """List current user's wishlist (product details)."""
        from bfg.shop.serializers.storefront import StorefrontProductSerializer

        workspace, customer = self._get_customer(request)
        entries = Wishlist.objects.filter(
            workspace=workspace,
            customer=customer
        ).select_related('product').prefetch_related(
            'product__media_links__media', 'product__variants', 'product__categories', 'product__tags'
        ).order_by('-created_at')
        products = [e.product for e in entries]
        serializer = StorefrontProductSerializer(
            products,
            many=True,
            context={'request': request}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='add')
    def add_product(self, request):
        """Add product to wishlist. Body: { "product": <id> }."""
        workspace, customer = self._get_customer(request)
        product_id = request.data.get('product')
        if product_id is None:
            raise ValidationError({'product': 'This field is required.'})
        try:
            product = Product.objects.get(id=product_id, workspace=workspace)
        except Product.DoesNotExist:
            raise NotFound("Product not found.")
        obj, created = Wishlist.objects.get_or_create(
            workspace=workspace,
            customer=customer,
            product=product,
            defaults={}
        )
        return Response(
            {'id': obj.id, 'product': product_id, 'created': created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='remove')
    def remove_product(self, request):
        """Remove product from wishlist. Body: { "product": <id> }."""
        workspace, customer = self._get_customer(request)
        product_id = request.data.get('product')
        if product_id is None:
            raise ValidationError({'product': 'This field is required.'})
        deleted, _ = Wishlist.objects.filter(
            workspace=workspace,
            customer=customer,
            product_id=product_id
        ).delete()
        return Response({'removed': deleted > 0}, status=status.HTTP_200_OK)

# -*- coding: utf-8 -*-
"""
Back-in-stock notification requests, for the back office.

Read and delete only. Rows are created by visitors through
``POST /api/v1/store/products/{id_or_slug}/notify-me/`` while the workspace's
out-of-stock policy is ``notify``; nothing in the admin should be inventing them.
"""
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound

from bfg.core.permissions import IsWorkspaceStaff
from bfg.shop.models import StockNotification


class StockNotificationSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    variant_name = serializers.CharField(source='variant.name', read_only=True, default=None)

    class Meta:
        model = StockNotification
        fields = [
            'id', 'product', 'product_name', 'product_sku', 'variant', 'variant_name',
            'email', 'customer', 'is_notified', 'notified_at', 'created_at',
        ]
        read_only_fields = fields


class StockNotificationViewSet(viewsets.ModelViewSet):
    """Admin view of who is waiting on what: list, filter by product, delete."""
    serializer_class = StockNotificationSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    http_method_names = ['get', 'delete', 'head', 'options']

    def get_queryset(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            raise NotFound("No workspace available.")
        qs = StockNotification.objects.filter(workspace=workspace).select_related(
            'product', 'variant', 'customer'
        ).order_by('-created_at')

        product_id = self.request.query_params.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)

        pending = self.request.query_params.get('pending')
        if pending and pending.lower() == 'true':
            qs = qs.filter(is_notified=False)
        return qs

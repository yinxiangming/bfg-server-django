"""
Quick product entry view — mobile staff use case.
Uses ProductService so the product.created global event is dispatched automatically.
"""
from decimal import Decimal

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from bfg.core.permissions import IsWorkspaceStaff
from bfg.shop.models import ProductCategory, ProductTag
from bfg.shop.services.product_service import ProductService


class QuickProductEntryView(APIView):
    """
    POST /api/v1/shop/products/quick-entry/

    Body (JSON):
        name          str   required  — product model / display name
        quantity      int   optional  — stock quantity, default 1
        location_code str   optional  — storage location code, stored as tag _loc:<code>
        category_id   int   optional  — ProductCategory id
        language      str   optional  — language code, default 'en'

    Returns 201 { id, name, slug } on success.

    Staff of *this workspace*, decided the same way as every other admin endpoint: an
    active StaffMember row. It used to check Django's `user.is_staff` — a global
    can-log-into-django-admin flag that has nothing to do with running a shop, so a
    tenant's own operators got 403 here while every other admin screen worked, and the
    only way to open it was to hand out a site-wide flag.
    """

    permission_classes = [permissions.IsAuthenticated, IsWorkspaceStaff]

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'detail': 'name 为必填项'}, status=400)

        try:
            quantity = max(1, int(request.data.get('quantity') or 1))
        except (TypeError, ValueError):
            quantity = 1

        location_code = (request.data.get('location_code') or '').strip()
        category_id = request.data.get('category_id')
        language = (request.data.get('language') or 'en').strip()
        workspace = request.workspace  # injected by WorkspaceMiddleware

        categories = []
        if category_id:
            try:
                categories = [
                    ProductCategory.objects.get(id=int(category_id), workspace=workspace)
                ]
            except (ProductCategory.DoesNotExist, TypeError, ValueError):
                pass

        service = ProductService(workspace=workspace, user=request.user)
        product = service.create_product(
            name=name,
            price=Decimal('0'),
            stock_quantity=quantity,
            categories=categories,
            language=language,
        )

        if location_code:
            tag, _ = ProductTag.objects.get_or_create(
                workspace=workspace,
                name=f'_loc:{location_code}',
            )
            product.tags.add(tag)

        return Response(
            {'id': product.id, 'name': product.name, 'slug': product.slug},
            status=201,
        )

# -*- coding: utf-8 -*-
"""Resolve freight rule price from product_id or direct price (for bfg.delivery calculator)."""

from decimal import Decimal
from typing import Any, Callable

from bfg.shop.models import Product
from bfg.shop.services.product_price_service import ProductPriceService


def get_freight_price_value(workspace) -> Callable[[Any], Decimal]:
    """
    Return a callable(price_config) -> Decimal for use as get_price_value in
    bfg.delivery.services.freight_calculator. Resolves product_id via ProductPriceService.
    """
    price_service = ProductPriceService()

    def _resolve(price_config: Any) -> Decimal:
        if isinstance(price_config, dict):
            product_id = price_config.get('product_id')
            if product_id:
                try:
                    product = Product.objects.get(id=product_id, is_active=True)
                    return price_service.get_effective_price(product)
                except Product.DoesNotExist:
                    raise ValueError(f"Product {product_id} not found or inactive")
            return Decimal(str(price_config.get('price', 0)))
        return Decimal(str(price_config))

    return _resolve

"""
BFG Shop Services

Service exports
"""

from .product_service import ProductService
from .product_identifier_service import (
    DEFAULT_SKU_PREFIX,
    DEFAULT_BARCODE_PREFIX,
    generate_identifier,
    get_workspace_identifier_prefixes,
    ensure_product_identifiers,
)
from .cart_service import CartService
from .order_service import OrderService
from .inventory_service import InventoryService
from .store_service import StoreService

__all__ = [
    'ProductService',
    'DEFAULT_SKU_PREFIX',
    'DEFAULT_BARCODE_PREFIX',
    'generate_identifier',
    'get_workspace_identifier_prefixes',
    'ensure_product_identifiers',
    'CartService',
    'OrderService',
    'InventoryService',
    'StoreService',
]

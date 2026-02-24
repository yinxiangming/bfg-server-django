"""
BFG Shop Module Exceptions

Module-specific exceptions for shop module
"""

from bfg.core.exceptions import BFGException


class InsufficientStock(BFGException):
    """Insufficient stock"""
    default_message = "Insufficient stock"
    default_code = "insufficient_stock"


class InvalidCoupon(BFGException):
    """Invalid coupon"""
    default_message = "Invalid coupon code"
    default_code = "invalid_coupon"


class EmptyCart(BFGException):
    """Empty cart"""
    default_message = "Cart is empty"
    default_code = "empty_cart"


class InvalidOrderStatus(BFGException):
    """Invalid order status"""
    default_message = "Invalid order status"
    default_code = "invalid_order_status"


class ProductNotFound(BFGException):
    """Product not found"""
    default_message = "Product not found"
    default_code = "product_not_found"


class OrderNotCancellable(BFGException):
    """Order cannot be cancelled"""
    default_message = "Order cannot be cancelled"
    default_code = "order_not_cancellable"

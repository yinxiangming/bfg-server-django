"""
BFG Delivery Module Exceptions

Module-specific exceptions for delivery module
"""

from bfg.core.exceptions import BFGException


class DeliveryUnavailable(BFGException):
    """Delivery service unavailable"""
    default_message = "Delivery service unavailable"
    default_code = "delivery_unavailable"

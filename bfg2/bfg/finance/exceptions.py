"""
BFG Finance Module Exceptions

Module-specific exceptions for finance module
"""

from bfg.core.exceptions import BFGException


class PaymentFailed(BFGException):
    """Payment failed"""
    default_message = "Payment failed"
    default_code = "payment_failed"


class GatewayNotConfigured(BFGException):
    """Payment gateway not configured"""
    default_message = "Payment gateway not configured"
    default_code = "gateway_not_configured"


class InsufficientFunds(BFGException):
    """Insufficient funds"""
    default_message = "Insufficient funds"
    default_code = "insufficient_funds"


class PaymentMethodInvalid(BFGException):
    """Saved payment method not usable (e.g. belongs to another Stripe customer)."""
    default_message = "This payment method is no longer valid. Please use a new card."
    default_code = "payment_method_invalid"

"""
Payment Gateway Plugins

Plugin-based payment gateway system. Each gateway is implemented as a plugin
in its own directory under gateways/.
"""

from .base import BasePaymentGateway, VALID_CLIENT_TYPES
from .loader import GatewayLoader, get_gateway_plugin, gateway_supports_client

__all__ = [
    'BasePaymentGateway',
    'VALID_CLIENT_TYPES',
    'GatewayLoader',
    'get_gateway_plugin',
    'gateway_supports_client',
]


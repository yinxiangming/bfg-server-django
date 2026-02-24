"""
Carrier Plugins

Plugin-based carrier system for shipping integrations.
Each carrier is implemented as a plugin in its own directory under carriers/.
"""

from .base import BaseCarrierPlugin
from .loader import CarrierLoader, get_carrier_plugin

__all__ = [
    'BaseCarrierPlugin',
    'CarrierLoader',
    'get_carrier_plugin',
]

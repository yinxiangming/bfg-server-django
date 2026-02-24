"""
Payment Gateway Plugin Loader

Discovers and loads payment gateway plugins from gateways/ directory
"""

import os
import importlib
from typing import Dict, Type, Optional, Any
from django.conf import settings
from bfg.finance.models import PaymentGateway
from .base import BasePaymentGateway


class GatewayLoader:
    """
    Payment gateway plugin loader
    
    Discovers and loads gateway plugins from gateways/ directory
    """
    
    _plugins: Dict[str, Type[BasePaymentGateway]] = {}
    _initialized = False
    
    @classmethod
    def discover_plugins(cls):
        """
        Discover all gateway plugins in gateways/ directory
        """
        if cls._initialized:
            return
        
        # Get gateways directory path
        gateways_dir = os.path.join(
            os.path.dirname(__file__),
            '..'
        )
        gateways_path = os.path.join(gateways_dir, 'gateways')
        
        if not os.path.exists(gateways_path):
            cls._initialized = True
            return
        
        # Discover plugin directories
        for item in os.listdir(gateways_path):
            plugin_path = os.path.join(gateways_path, item)
            
            # Skip if not a directory or is special directory
            if not os.path.isdir(plugin_path) or item.startswith('_'):
                continue
            
            # Try to import plugin
            try:
                plugin_module = importlib.import_module(
                    f'bfg.finance.gateways.{item}.plugin'
                )
                
                # Look for plugin class (should be named GatewayPlugin or similar)
                plugin_class = None
                for attr_name in dir(plugin_module):
                    attr = getattr(plugin_module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, BasePaymentGateway) and
                        attr != BasePaymentGateway):
                        plugin_class = attr
                        break
                
                if plugin_class and plugin_class.gateway_type:
                    cls._plugins[plugin_class.gateway_type] = plugin_class
                    
            except (ImportError, AttributeError) as e:
                # Plugin not properly configured, skip
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to load gateway plugin {item}: {e}")
                continue
        
        cls._initialized = True
    
    @classmethod
    def get_plugin_class(cls, gateway_type: str) -> Optional[Type[BasePaymentGateway]]:
        """
        Get plugin class for gateway type
        
        Args:
            gateway_type: Gateway type (e.g., 'stripe', 'paypal')
        
        Returns:
            Type[BasePaymentGateway] or None
        """
        cls.discover_plugins()
        return cls._plugins.get(gateway_type)
    
    @classmethod
    def get_plugin(cls, gateway: PaymentGateway) -> Optional[BasePaymentGateway]:
        """
        Get plugin instance for gateway
        
        Args:
            gateway: PaymentGateway model instance
        
        Returns:
            BasePaymentGateway instance or None
        """
        plugin_class = cls.get_plugin_class(gateway.gateway_type)
        if not plugin_class:
            return None
        
        try:
            return plugin_class(gateway)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to initialize gateway plugin {gateway.gateway_type}: {e}")
            return None
    
    @classmethod
    def list_available_plugins(cls) -> Dict[str, str]:
        """
        List all available gateway plugins
        
        Returns:
            dict: {gateway_type: display_name}
        """
        cls.discover_plugins()
        return {
            gateway_type: plugin_class.display_name or gateway_type
            for gateway_type, plugin_class in cls._plugins.items()
        }
    
    @classmethod
    def get_plugin_info(cls, gateway_type: str) -> Optional[Dict[str, Any]]:
        """
        Get plugin information
        
        Args:
            gateway_type: Gateway type
        
        Returns:
            dict: Plugin info or None
        """
        plugin_class = cls.get_plugin_class(gateway_type)
        if not plugin_class:
            return None
        
        # Get config schema - plugins should implement get_config_schema as instance method
        # We'll create a minimal instance to get the schema
        config_schema = {}
        try:
            # Create a minimal mock gateway for schema retrieval
            class MockGateway:
                def __init__(self, gateway_type):
                    self.gateway_type = gateway_type
                    self.config = {}
            
            mock_gateway = MockGateway(plugin_class.gateway_type)
            # Create plugin instance without calling __init__ validation
            plugin_instance = object.__new__(plugin_class)
            plugin_instance.gateway = mock_gateway
            plugin_instance.config = {}
            config_schema = plugin_instance.get_config_schema()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to get config schema for {plugin_class.gateway_type}: {e}")
        
        return {
            'gateway_type': plugin_class.gateway_type,
            'display_name': plugin_class.display_name,
            'supported_methods': plugin_class.supported_methods,
            'supported_clients': getattr(plugin_class, 'supported_clients', []) or [],
            'config_schema': config_schema,
        }


def gateway_supports_client(gateway_type: str, client: str) -> bool:
    """
    Return True if the gateway plugin supports the given client type.
    Empty supported_clients means all clients are supported.
    """
    if not client:
        return True
    plugin_info = GatewayLoader.get_plugin_info(gateway_type)
    if not plugin_info:
        return False
    supported = plugin_info.get('supported_clients') or []
    return len(supported) == 0 or client in supported


def get_gateway_plugin(gateway: PaymentGateway) -> Optional[BasePaymentGateway]:
    """
    Convenience function to get gateway plugin instance
    
    Args:
        gateway: PaymentGateway model instance
    
    Returns:
        BasePaymentGateway instance or None
    """
    return GatewayLoader.get_plugin(gateway)


"""
Carrier Plugin Loader

Discovers and loads carrier plugins from carriers/ directory.
"""

import os
import importlib
import logging
from typing import Dict, Type, Optional, Any

from .base import BaseCarrierPlugin

logger = logging.getLogger(__name__)


class CarrierLoader:
    """
    Carrier plugin loader.
    
    Discovers and loads carrier plugins from carriers/ directory.
    """
    
    _plugins: Dict[str, Type[BaseCarrierPlugin]] = {}
    _initialized = False
    
    @classmethod
    def discover_plugins(cls):
        """
        Discover all carrier plugins in carriers/ directory.
        """
        if cls._initialized:
            return
        
        # Get carriers directory path
        carriers_path = os.path.dirname(__file__)
        
        if not os.path.exists(carriers_path):
            cls._initialized = True
            return
        
        # Discover plugin directories
        for item in os.listdir(carriers_path):
            plugin_path = os.path.join(carriers_path, item)
            
            # Skip if not a directory or is special directory
            if not os.path.isdir(plugin_path) or item.startswith('_'):
                continue
            
            # Skip __pycache__
            if item == '__pycache__':
                continue
            
            # Try to import plugin
            try:
                plugin_module = importlib.import_module(
                    f'bfg.delivery.carriers.{item}.plugin'
                )
                
                # Look for plugin class (should inherit from BaseCarrierPlugin)
                plugin_class = None
                for attr_name in dir(plugin_module):
                    attr = getattr(plugin_module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, BaseCarrierPlugin) and
                        attr != BaseCarrierPlugin):
                        plugin_class = attr
                        break
                
                if plugin_class and plugin_class.carrier_type:
                    cls._plugins[plugin_class.carrier_type] = plugin_class
                    logger.info(f"Loaded carrier plugin: {plugin_class.carrier_type}")
                    
            except (ImportError, AttributeError) as e:
                # Plugin not properly configured, skip
                logger.warning(f"Failed to load carrier plugin {item}: {e}")
                continue
        
        cls._initialized = True
    
    @classmethod
    def get_plugin_class(cls, carrier_type: str) -> Optional[Type[BaseCarrierPlugin]]:
        """
        Get plugin class for carrier type.
        
        Args:
            carrier_type: Carrier type (e.g., 'parcelport', 'nzpost')
        
        Returns:
            Type[BaseCarrierPlugin] or None
        """
        cls.discover_plugins()
        return cls._plugins.get(carrier_type)
    
    @classmethod
    def get_plugin(cls, carrier) -> Optional[BaseCarrierPlugin]:
        """
        Get plugin instance for carrier.
        
        Args:
            carrier: Carrier model instance
        
        Returns:
            BaseCarrierPlugin instance or None
        """
        if not carrier.carrier_type:
            logger.warning(f"Carrier {carrier.name} (ID: {carrier.id}) has no carrier_type set")
            return None
        
        # Try exact match first
        plugin_class = cls.get_plugin_class(carrier.carrier_type)
        
        # If not found, try case-insensitive match
        if not plugin_class:
            carrier_type_lower = carrier.carrier_type.lower().strip()
            for plugin_type, plugin_cls in cls._plugins.items():
                if plugin_type.lower().strip() == carrier_type_lower:
                    plugin_class = plugin_cls
                    logger.warning(
                        f"Carrier type '{carrier.carrier_type}' matched plugin '{plugin_type}' "
                        f"(case-insensitive). Consider updating carrier_type to '{plugin_type}'"
                    )
                    break
        
        if not plugin_class:
            available_types = ', '.join(cls._plugins.keys())
            logger.warning(
                f"No plugin found for carrier type '{carrier.carrier_type}'. "
                f"Available types: {available_types}"
            )
            return None
        
        try:
            return plugin_class(carrier)
        except ValueError as e:
            # Configuration or type mismatch errors
            error_msg = str(e)
            if 'type mismatch' in error_msg.lower():
                logger.error(
                    f"Carrier type mismatch for {carrier.name} (ID: {carrier.id}): "
                    f"carrier_type='{carrier.carrier_type}', expected='{plugin_class.carrier_type}'. "
                    f"Error: {error_msg}"
                )
            else:
                logger.error(
                    f"Failed to initialize carrier plugin {carrier.carrier_type} for "
                    f"{carrier.name} (ID: {carrier.id}): {error_msg}"
                )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error initializing carrier plugin {carrier.carrier_type} for "
                f"{carrier.name} (ID: {carrier.id}): {e}",
                exc_info=True
            )
            return None
    
    @classmethod
    def list_available_plugins(cls) -> Dict[str, str]:
        """
        List all available carrier plugins.
        
        Returns:
            dict: {carrier_type: display_name}
        """
        cls.discover_plugins()
        return {
            carrier_type: plugin_class.display_name or carrier_type
            for carrier_type, plugin_class in cls._plugins.items()
        }
    
    @classmethod
    def get_plugin_info(cls, carrier_type: str) -> Optional[Dict[str, Any]]:
        """
        Get plugin information.
        
        Args:
            carrier_type: Carrier type
        
        Returns:
            dict: Plugin info or None
        """
        plugin_class = cls.get_plugin_class(carrier_type)
        if not plugin_class:
            return None
        
        # Get config schema - plugins should implement get_config_schema
        config_schema = {}
        try:
            # Create a minimal mock carrier for schema retrieval
            class MockCarrier:
                def __init__(self, carrier_type):
                    self.carrier_type = carrier_type
                    self.config = {}
                    self.test_config = {}
                    self.is_test_mode = False
                    self.tracking_url_template = ''
                
                def get_active_config(self):
                    return {}
            
            mock_carrier = MockCarrier(plugin_class.carrier_type)
            # Create plugin instance without full validation
            plugin_instance = object.__new__(plugin_class)
            plugin_instance.carrier = mock_carrier
            plugin_instance.config = {}
            config_schema = plugin_instance.get_config_schema()
        except Exception as e:
            logger.warning(f"Failed to get config schema for {plugin_class.carrier_type}: {e}")
        
        return {
            'carrier_type': plugin_class.carrier_type,
            'display_name': plugin_class.display_name,
            'supported_countries': plugin_class.supported_countries,
            'config_schema': config_schema,
        }
    
    @classmethod
    def reload_plugins(cls):
        """
        Force reload all plugins.
        """
        cls._plugins = {}
        cls._initialized = False
        cls.discover_plugins()


def get_carrier_plugin(carrier) -> Optional[BaseCarrierPlugin]:
    """
    Convenience function to get carrier plugin instance.
    
    Args:
        carrier: Carrier model instance
    
    Returns:
        BaseCarrierPlugin instance or None
    """
    return CarrierLoader.get_plugin(carrier)

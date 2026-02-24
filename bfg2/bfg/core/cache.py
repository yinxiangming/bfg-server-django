"""
BFG Cache Utilities

Cache management utilities
"""

from django.core.cache import cache
from django.utils.encoding import force_str
import hashlib
from typing import Optional, Any


class CacheMixin:
    """
    Common cache Mixin
    
    Provides unified cache interface
    """
    cache_timeout = 300  # Default 5 minutes
    cache_key_prefix = ''
    
    def get_cache_key(self, **kwargs) -> str:
        """
        Generate cache key
        
        Args:
            **kwargs: Key-value parameters
            
        Returns:
            str: Cache key
        """
        key_parts = [self.cache_key_prefix]
        
        # Sort to ensure key consistency
        for k in sorted(kwargs.keys()):
            v = kwargs[k]
            if v is not None:
                key_parts.append(f"{k}:{force_str(v)}")
        
        key = ':'.join(key_parts)
        
        # Use hash if key is too long
        if len(key) > 200:
            key = f"{self.cache_key_prefix}:{hashlib.md5(key.encode()).hexdigest()}"
        
        return key
    
    def get_cached_data(self, key: str) -> Optional[Any]:
        """
        Get cached data
        
        Args:
            key: Cache key
            
        Returns:
            Cached data or None
        """
        return cache.get(key)
    
    def set_cached_data(self, key: str, data: Any, timeout: Optional[int] = None):
        """
        Set cached data
        
        Args:
            key: Cache key
            data: Data to cache
            timeout: Expiration time (seconds), None uses default
        """
        if timeout is None:
            timeout = self.cache_timeout
        cache.set(key, data, timeout)
    
    def invalidate_cache(self, key: str):
        """
        Invalidate cache
        
        Args:
            key: Cache key
        """
        cache.delete(key)
    
    def invalidate_pattern(self, pattern: str):
        """
        Delete all caches matching pattern
        
        Requires Redis support
        
        Args:
            pattern: Match pattern (e.g., 'products:workspace:1:*')
        """
        # Requires Redis support
        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern(pattern)
        else:
            # Fallback: Cache backend doesn't support pattern deletion
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Cache backend does not support pattern deletion: {pattern}"
            )


class CacheService:
    """
    Cache service class
    
    Provides common cache operations
    """
    
    @staticmethod
    def get(key: str, default=None) -> Any:
        """Get cache"""
        return cache.get(key, default)
    
    @staticmethod
    def set(key: str, value: Any, timeout: int = 300):
        """Set cache"""
        cache.set(key, value, timeout)
    
    @staticmethod
    def delete(key: str):
        """Delete cache"""
        cache.delete(key)
    
    @staticmethod
    def clear():
        """Clear all caches"""
        cache.clear()
    
    @staticmethod
    def get_or_set(key: str, default_func, timeout: int = 300) -> Any:
        """
        Get cache, if doesn't exist call function and cache result
        
        Args:
            key: Cache key
            default_func: Default value function
            timeout: Expiration time
            
        Returns:
            Cached value or function return value
        """
        cached = cache.get(key)
        if cached is not None:
            return cached
        
        value = default_func()
        cache.set(key, value, timeout)
        return value

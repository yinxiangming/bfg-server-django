"""
BFG Common Module Services

Settings management service
"""

from typing import Any, Dict
from bfg.core.services import BaseService
from bfg.common.models import Settings, Workspace


class SettingsService(BaseService):
    """
    Workspace settings management service
    
    Handles workspace-specific configuration settings
    """
    
    def get_or_create_settings(self, workspace: Workspace) -> Settings:
        """
        Get or create settings for workspace
        
        Args:
            workspace: Workspace instance
            
        Returns:
            Settings: Settings instance
        """
        self.validate_workspace_access(workspace)
        
        settings, created = Settings.objects.get_or_create(
            workspace=workspace,
            defaults={
                'default_language': 'en',
                'default_currency': 'NZD',
                'default_timezone': 'UTC',
                'supported_languages': ['en'],
                'features': {},
            }
        )
        
        return settings
    
    def update_settings(self, settings: Settings, **kwargs: Any) -> Settings:
        """
        Update workspace settings
        
        Args:
            settings: Settings instance
            **kwargs: Fields to update
            
        Returns:
            Settings: Updated settings instance
        """
        self.validate_workspace_access(settings)
        
        # Update allowed fields
        allowed_fields = [
            'site_name', 'site_description', 'logo', 'favicon',
            'default_language', 'supported_languages', 'default_currency',
            'default_timezone', 'contact_email', 'support_email',
            'contact_phone', 'facebook_url', 'twitter_url', 'instagram_url',
            'features', 'custom_settings'
        ]
        
        for key, value in kwargs.items():
            if key in allowed_fields and hasattr(settings, key):
                setattr(settings, key, value)
        
        settings.save()
        return settings
    
    def enable_feature(self, settings: Settings, feature_name: str) -> Settings:
        """
        Enable a feature for workspace
        
        Args:
            settings: Settings instance
            feature_name: Feature name (e.g., 'shop', 'blog')
            
        Returns:
            Settings: Updated settings instance
        """
        self.validate_workspace_access(settings)
        
        if not settings.features:
            settings.features = {}
        
        settings.features[feature_name] = True
        settings.save()
        
        return settings
    
    def disable_feature(self, settings: Settings, feature_name: str) -> Settings:
        """
        Disable a feature for workspace
        
        Args:
            settings: Settings instance
            feature_name: Feature name
            
        Returns:
            Settings: Updated settings instance
        """
        self.validate_workspace_access(settings)
        
        if settings.features and feature_name in settings.features:
            settings.features[feature_name] = False
            settings.save()
        
        return settings
    
    def is_feature_enabled(self, settings: Settings, feature_name: str) -> bool:
        """
        Check if a feature is enabled
        
        Args:
            settings: Settings instance
            feature_name: Feature name
            
        Returns:
            bool: True if enabled
        """
        if not settings.features:
            return False
        
        return settings.features.get(feature_name, False)

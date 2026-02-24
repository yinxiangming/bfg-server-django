"""
BFG Web Module Services

Site management service
"""

from typing import Any
from django.db import transaction
from django.utils.text import slugify
from bfg.core.services import BaseService
from bfg.web.exceptions import SiteNotFound
from bfg.web.models import Site


class SiteService(BaseService):
    """
    Site management service
    
    Handles multi-site configuration and domain management
    """
    
    @transaction.atomic
    def create_site(self, name: str, domain: str, **kwargs: Any) -> Site:
        """
        Create new site with default configuration
        
        Args:
            name: Site name
            domain: Domain name (e.g., 'example.com')
            **kwargs: Additional site fields
            
        Returns:
            Site: Created site instance
        """
        # Check if domain already exists
        if Site.objects.filter(domain=domain).exists():
            from bfg.core.exceptions import ValidationError
            raise ValidationError(f"Domain '{domain}' already exists")
        
        # Create site
        site = Site.objects.create(
            workspace=self.workspace,
            name=name,
            domain=domain,
            site_title=kwargs.get('site_title', name),
            site_description=kwargs.get('site_description', ''),
            default_language=kwargs.get('default_language', 'en'),
            languages=kwargs.get('languages', ['en']),
            is_active=kwargs.get('is_active', True),
            is_default=kwargs.get('is_default', False),
        )
        
        # If this is the first site or marked as default, set as default
        if site.is_default:
            self.set_default_site(site)
        
        return site
    
    def get_site_by_domain(self, domain: str) -> Site:
        """
        Get site by domain name
        
        Args:
            domain: Domain name
            
        Returns:
            Site: Site instance
            
        Raises:
            SiteNotFound: If site doesn't exist
        """
        try:
            site = Site.objects.get(domain=domain, is_active=True)
            self.validate_workspace_access(site)
            return site
        except Site.DoesNotExist:
            raise SiteNotFound(f"Site with domain '{domain}' not found")
    
    def update_site(self, site: Site, **kwargs: Any) -> Site:
        """
        Update site settings
        
        Args:
            site: Site instance
            **kwargs: Fields to update
            
        Returns:
            Site: Updated site instance
        """
        self.validate_workspace_access(site)
        
        for key, value in kwargs.items():
            if hasattr(site, key) and key not in ['id', 'workspace', 'domain']:
                setattr(site, key, value)
        
        site.save()
        return site
    
    @transaction.atomic
    def set_default_site(self, site: Site) -> Site:
        """
        Set site as default (unset others)
        
        Args:
            site: Site instance to set as default
            
        Returns:
            Site: Updated site instance
        """
        self.validate_workspace_access(site)
        
        # Unset all other default sites for this workspace
        Site.objects.filter(
            workspace=self.workspace,
            is_default=True
        ).exclude(id=site.id).update(is_default=False)
        
        site.is_default = True
        site.save()
        
        return site
    
    def deactivate_site(self, site: Site) -> Site:
        """
        Deactivate site
        
        Args:
            site: Site instance
            
        Returns:
            Site: Updated site instance
        """
        self.validate_workspace_access(site)
        
        site.is_active = False
        site.save()
        
        return site

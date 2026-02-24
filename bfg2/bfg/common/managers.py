# -*- coding: utf-8 -*-
"""
Custom model managers for BFG Common models.
"""

from django.db import models


class WorkspaceManager(models.Manager):
    """Manager for Workspace model with custom querysets."""
    
    def active(self):
        """Return only active workspaces."""
        return self.filter(is_active=True)


class CustomerManager(models.Manager):
    """Manager for Customer model with workspace filtering."""
    
    def active(self):
        """Return only active customers."""
        return self.filter(is_active=True)
    
    def verified(self):
        """Return only verified customers."""
        return self.filter(is_verified=True)
    
    def for_workspace(self, workspace):
        """Return customers for a specific workspace."""
        return self.filter(workspace=workspace)


class AddressManager(models.Manager):
    """Manager for Address model."""
    
    def shipping(self):
        """Return only shipping addresses."""
        return self.filter(address_type__in=['shipping', 'both'])
    
    def billing(self):
        """Return only billing addresses."""
        return self.filter(address_type__in=['billing', 'both'])
    
    def defaults(self):
        """Return only default addresses."""
        return self.filter(is_default=True)

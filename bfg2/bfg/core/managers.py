"""
BFG Base Manager

Base class for all custom Manager classes
"""

from django.db import models


class WorkspaceManager(models.Manager):
    """
    Workspace Manager base class
    
    Automatically filters workspace data
    """
    
    def __init__(self, *args, **kwargs):
        self._workspace = None
        super().__init__(*args, **kwargs)
    
    def for_workspace(self, workspace):
        """
        Set workspace filter
        
        Args:
            workspace: Workspace object or workspace ID
            
        Returns:
            QuerySet
        """
        workspace_id = workspace.id if hasattr(workspace, 'id') else workspace
        return self.filter(workspace_id=workspace_id)
    
    def active(self):
        """
        Return only active records
        
        Returns:
            QuerySet
        """
        if hasattr(self.model, 'is_active'):
            return self.filter(is_active=True)
        return self.all()
    
    def published(self):
        """
        Return only published records
        
        Returns:
            QuerySet
        """
        if hasattr(self.model, 'status'):
            return self.filter(status='published')
        return self.all()


class BaseManager(models.Manager):
    """
    Base Manager class
    
    Provides common query methods
    """
    
    def get_or_none(self, **kwargs):
        """
        Get object or return None
        
        Args:
            **kwargs: Query conditions
            
        Returns:
            Object instance or None
        """
        try:
            return self.get(**kwargs)
        except self.model.DoesNotExist:
            return None
    
    def bulk_create_or_update(self, objects, update_fields=None):
        """
        Bulk create or update objects
        
        Args:
            objects: List of objects
            update_fields: List of fields to update
            
        Returns:
            List of created/updated objects
        """
        if not objects:
            return []
        
        # Simplified version, can be optimized in production
        results = []
        for obj in objects:
            if obj.pk:
                # Update
                if update_fields:
                    for field in update_fields:
                        setattr(obj, field, getattr(obj, field))
                obj.save(update_fields=update_fields)
            else:
                # Create
                obj.save()
            results.append(obj)
        
        return results

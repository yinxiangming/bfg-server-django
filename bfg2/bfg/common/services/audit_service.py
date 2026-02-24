"""
BFG Core Audit Service

Service for logging audit trails
"""

from typing import Any, Optional, Dict
from django.contrib.contenttypes.models import ContentType
from bfg.core.services import BaseService
from bfg.common.models import AuditLog


class AuditService(BaseService):
    """
    Audit logging service
    
    Automatically logs important actions and changes
    """
    
    def log_action(
        self,
        action: str,
        obj: Optional[Any] = None,
        description: str = '',
        changes: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AuditLog:
        """
        Log an audit action
        
        Args:
            action: Action type ('create', 'update', 'delete', etc.)
            obj: Object being acted upon
            description: Human-readable description
            changes: Dictionary of changes
            **kwargs: Additional fields (ip_address, user_agent)
            
        Returns:
            AuditLog: Created audit log instance
        """
        audit_log = AuditLog.objects.create(
            workspace=self.workspace,
            user=self.user,
            action=action,
            content_type=ContentType.objects.get_for_model(obj) if obj else None,
            object_id=obj.pk if obj else None,
            object_repr=str(obj) if obj else '',
            description=description,
            changes=changes or {},
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent', ''),
        )
        
        return audit_log
    
    def log_create(self, obj: Any, description: str = '', **kwargs: Any) -> AuditLog:
        """Log object creation"""
        return self.log_action('create', obj, description or f"Created {obj}", **kwargs)
    
    def log_update(
        self,
        obj: Any,
        changes: Dict[str, Any],
        description: str = '',
        **kwargs: Any
    ) -> AuditLog:
        """
        Log object update
        
        Args:
            obj: Updated object
            changes: Dict of changes {'field': {'old': value, 'new': value}}
            description: Description
            
        Returns:
            AuditLog: Created audit log
        """
        return self.log_action(
            'update',
            obj,
            description or f"Updated {obj}",
            changes=changes,
            **kwargs
        )
    
    def log_delete(self, obj: Any, description: str = '', **kwargs: Any) -> AuditLog:
        """Log object deletion"""
        return self.log_action('delete', obj, description or f"Deleted {obj}", **kwargs)
    
    def log_login(self, description: str = '', **kwargs: Any) -> AuditLog:
        """Log user login"""
        return self.log_action('login', None, description or f"{self.user} logged in", **kwargs)
    
    def log_logout(self, description: str = '', **kwargs: Any) -> AuditLog:
        """Log user logout"""
        return self.log_action('logout', None, description or f"{self.user} logged out", **kwargs)
    
    def get_object_history(self, obj: Any) -> 'QuerySet[AuditLog]':
        """
        Get audit history for an object
        
        Args:
            obj: Object to get history for
            
        Returns:
            QuerySet: AuditLog queryset
        """
        content_type = ContentType.objects.get_for_model(obj)
        
        return AuditLog.objects.filter(
            workspace=self.workspace,
            content_type=content_type,
            object_id=obj.pk
        ).order_by('-created_at')

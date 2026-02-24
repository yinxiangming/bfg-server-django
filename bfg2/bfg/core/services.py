"""
BFG Base Service

Base class for all Service classes
"""

from django.db import transaction
from typing import Optional
from .events import global_dispatcher
from .exceptions import PermissionDenied


class BaseService:
    """
    Base class for all Service classes
    Provides common transaction management and event dispatching
    """
    
    def __init__(self, workspace=None, user=None):
        """
        Initialize Service
        
        Args:
            workspace: Workspace object
            user: Current user object
        """
        self.workspace = workspace
        self.user = user
        self.events = global_dispatcher
    
    @transaction.atomic
    def execute_in_transaction(self, func, *args, **kwargs):
        """
        Execute method within a transaction
        
        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function execution result
        """
        return func(*args, **kwargs)
    
    def emit_event(self, event_name: str, data: dict):
        """
        Emit business event
        
        Args:
            event_name: Event name (e.g., 'order.created')
            data: Event data
        """
        event_data = {
            'workspace': self.workspace,
            'user': self.user,
            'data': data
        }
        self.events.dispatch(event_name, event_data)
    
    def validate_workspace_access(self, obj):
        """
        Validate that object belongs to current workspace
        
        Args:
            obj: Object to validate
            
        Raises:
            PermissionDenied: If object doesn't belong to current workspace
            
        Returns:
            bool: True if valid
        """
        if not hasattr(obj, 'workspace_id'):
            return True
        
        if self.workspace and obj.workspace_id != self.workspace.id:
            raise PermissionDenied(
                "Access denied: object belongs to different workspace"
            )
        
        return True
    
    def validate_customer_access(self, obj, customer):
        """
        Validate that object belongs to specified customer
        
        Args:
            obj: Object to validate
            customer: Customer object
            
        Raises:
            PermissionDenied: If object doesn't belong to specified customer
            
        Returns:
            bool: True if valid
        """
        if hasattr(obj, 'customer_id'):
            if obj.customer_id != customer.id:
                raise PermissionDenied(
                    "Access denied: you can only access your own data"
                )
        
        return True
    
    def get_or_404(self, model_class, **filters):
        """
        Get object or raise 404 exception
        
        Args:
            model_class: Model class
            **filters: Query filter conditions
            
        Returns:
            Object instance
            
        Raises:
            NotFound: Object not found
        """
        from .exceptions import NotFound
        
        try:
            return model_class.objects.get(**filters)
        except model_class.DoesNotExist:
            raise NotFound(
                f"{model_class.__name__} not found"
            )

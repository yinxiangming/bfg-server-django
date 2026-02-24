"""
BFG Shop Module Services

Store management service
"""

from typing import Any, Optional
from django.db import transaction
from bfg.core.services import BaseService
from bfg.shop.models import Store
from bfg.delivery.models import Warehouse


class StoreService(BaseService):
    """
    Store management service
    
    Handles store creation and management (requires admin permissions)
    """
    
    @transaction.atomic
    def create_store(
        self,
        name: str,
        code: str,
        **kwargs: Any
    ) -> Store:
        """
        Create new store
        
        Args:
            name: Store name
            code: Store code (unique per workspace)
            **kwargs: Additional store fields
            
        Returns:
            Store: Created store instance
        """
        from bfg.core.exceptions import ValidationError
        
        # Check code uniqueness
        if Store.objects.filter(workspace=self.workspace, code=code).exists():
            raise ValidationError(f"Store with code '{code}' already exists")
        
        store = Store.objects.create(
            workspace=self.workspace,
            name=name,
            code=code,
            description=kwargs.get('description', ''),
            settings=kwargs.get('settings', {}),
            is_active=kwargs.get('is_active', True),
        )
        
        # Link warehouses if provided
        if 'warehouse_ids' in kwargs:
            warehouses = Warehouse.objects.filter(
                workspace=self.workspace,
                id__in=kwargs['warehouse_ids']
            )
            store.warehouses.set(warehouses)
        
        # Emit event
        self.emit_event('store.created', {'store': store})
        
        return store
    
    def update_store(self, store: Store, **kwargs: Any) -> Store:
        """
        Update store information
        
        Args:
            store: Store instance
            **kwargs: Fields to update
            
        Returns:
            Store: Updated store instance
        """
        self.validate_workspace_access(store)
        
        # Handle warehouses separately
        warehouse_ids = kwargs.pop('warehouse_ids', None)
        
        for key, value in kwargs.items():
            if hasattr(store, key) and key not in ['id', 'workspace', 'code']:
                setattr(store, key, value)
        
        store.save()
        
        # Update warehouses if provided
        if warehouse_ids is not None:
            warehouses = Warehouse.objects.filter(
                workspace=self.workspace,
                id__in=warehouse_ids
            )
            store.warehouses.set(warehouses)
        
        return store
    
    def add_warehouse(self, store: Store, warehouse: Warehouse) -> Store:
        """
        Add warehouse to store
        
        Args:
            store: Store instance
            warehouse: Warehouse instance
            
        Returns:
            Store: Updated store instance
        """
        self.validate_workspace_access(store)
        self.validate_workspace_access(warehouse)
        
        store.warehouses.add(warehouse)
        
        return store
    
    def remove_warehouse(self, store: Store, warehouse: Warehouse) -> Store:
        """
        Remove warehouse from store
        
        Args:
            store: Store instance
            warehouse: Warehouse instance
            
        Returns:
            Store: Updated store instance
        """
        self.validate_workspace_access(store)
        
        store.warehouses.remove(warehouse)
        
        return store
    
    def deactivate_store(self, store: Store) -> Store:
        """
        Deactivate store
        
        Args:
            store: Store instance
            
        Returns:
            Store: Updated store instance
        """
        self.validate_workspace_access(store)
        
        store.is_active = False
        store.save()
        
        return store

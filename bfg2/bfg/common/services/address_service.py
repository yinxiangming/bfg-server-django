"""
BFG Common Module Services

Address management service
"""

from typing import Any, Optional
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet, Model
from bfg.core.services import BaseService
from bfg.core.exceptions import NotFound
from bfg.common.models import Address


class AddressService(BaseService):
    """
    Address management service
    
    Handles address creation and management for any model using GenericForeignKey
    """
    
    @transaction.atomic
    def create_address(self, content_object: Model, **address_data: Any) -> Address:
        """
        Create address for any object (Customer, Store, Warehouse, etc.)
        
        Args:
            content_object: Object to attach address to (must have 'workspace' attribute)
            **address_data: Address fields
            
        Returns:
            Address: Created address instance
        """
        # Get workspace from content_object
        workspace = getattr(content_object, 'workspace', self.workspace)
        
        # Get ContentType for the object
        content_type = ContentType.objects.get_for_model(content_object)
        
        # Handle default address logic
        is_default = address_data.get('is_default', False)
        
        if is_default:
            # Set all other addresses for this object to non-default
            Address.objects.filter(
                workspace=workspace,
                content_type=content_type,
                object_id=content_object.id,
                is_default=True
            ).update(is_default=False)
        
        # Create address
        address = Address.objects.create(
            workspace=workspace,
            content_type=content_type,
            object_id=content_object.id,
            full_name=address_data.get('full_name', ''),
            phone=address_data.get('phone', ''),
            email=address_data.get('email', ''),
            address_line1=address_data.get('address_line1', ''),
            address_line2=address_data.get('address_line2', ''),
            city=address_data.get('city', ''),
            state=address_data.get('state', ''),
            postal_code=address_data.get('postal_code', ''),
            country=address_data.get('country', ''),
            latitude=address_data.get('latitude'),
            longitude=address_data.get('longitude'),
            notes=address_data.get('notes', ''),
            is_default=is_default,
        )
        
        return address
    
    def get_addresses_for_object(self, content_object: Model) -> QuerySet[Address]:
        """
        Get all addresses for an object
        
        Args:
            content_object: Object to get addresses for
            
        Returns:
            QuerySet: Address queryset
        """
        content_type = ContentType.objects.get_for_model(content_object)
        workspace = getattr(content_object, 'workspace', self.workspace)
        
        return Address.objects.filter(
            workspace=workspace,
            content_type=content_type,
            object_id=content_object.id
        ).order_by('-is_default', '-created_at')
    
    def get_default_address(self, content_object: Model) -> Optional[Address]:
        """
        Get default address for an object
        
        Args:
            content_object: Object to get default address for
            
        Returns:
            Address or None: Default address if exists
        """
        addresses = self.get_addresses_for_object(content_object)
        return addresses.filter(is_default=True).first()
    
    def update_address(self, address: Address, **kwargs: Any) -> Address:
        """
        Update address information
        
        Args:
            address: Address instance
            **kwargs: Fields to update
            
        Returns:
            Address: Updated address instance
        """
        self.validate_workspace_access(address)
        
        # Handle is_default updates
        if 'is_default' in kwargs and kwargs['is_default']:
            # Set all other addresses for same object to non-default
            Address.objects.filter(
                workspace=address.workspace,
                content_type=address.content_type,
                object_id=address.object_id,
                is_default=True
            ).exclude(id=address.id).update(is_default=False)
        
        for key, value in kwargs.items():
            if hasattr(address, key) and key not in ['id', 'workspace', 'content_type', 'object_id']:
                setattr(address, key, value)
        
        address.save()
        return address
    
    def delete_address(self, address: Address) -> None:
        """
        Delete address
        
        Args:
            address: Address instance
        """
        self.validate_workspace_access(address)
        
        # If deleting default address, set another one as default
        if address.is_default:
            other_address = Address.objects.filter(
                workspace=address.workspace,
                content_type=address.content_type,
                object_id=address.object_id
            ).exclude(id=address.id).first()
            
            if other_address:
                other_address.is_default = True
                other_address.save()
        
        address.delete()

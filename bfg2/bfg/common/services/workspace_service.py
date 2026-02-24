"""
BFG Common Module Services

Workspace management service
"""

from typing import Optional, Dict, Any
from django.db import transaction
from django.utils.text import slugify
from bfg.core.services import BaseService
from bfg.common.exceptions import WorkspaceAlreadyExists
from bfg.common.models import Workspace, StaffRole, StaffMember, User


class WorkspaceService(BaseService):
    """
    Workspace management service
    
    Handles workspace creation, updates, and initialization
    """
    
    @transaction.atomic
    def create_workspace(
        self, 
        name: str, 
        slug: Optional[str] = None, 
        owner_user: Optional[User] = None, 
        **kwargs: Any
    ) -> Workspace:
        """
        Create a new workspace with default roles
        
        Args:
            name: Workspace name
            slug: Workspace slug (auto-generated if not provided)
            owner_user: User to be assigned as workspace owner
            **kwargs: Additional workspace fields
            
        Returns:
            Workspace: Created workspace instance
            
        Raises:
            WorkspaceAlreadyExists: If workspace with slug already exists
        """
        # Generate slug if not provided
        if not slug:
            slug = slugify(name)
        
        # Check if workspace already exists
        if Workspace.objects.filter(slug=slug).exists():
            raise WorkspaceAlreadyExists(f"Workspace with slug '{slug}' already exists")
        
        # Create workspace
        workspace = Workspace.objects.create(
            name=name,
            slug=slug,
            is_active=kwargs.get('is_active', True),
            **{k: v for k, v in kwargs.items() if k != 'is_active'}
        )

        # Emit workspace created event - modules will respond to initialize their data
        # This must happen before assigning owner, as owner assignment requires admin role
        self.emit_event('workspace.created', {'workspace': workspace})

        # Assign owner if provided (after roles are created via event)
        if owner_user:
            self._assign_workspace_owner(workspace, owner_user)
        
        return workspace
    

    def _assign_workspace_owner(self, workspace: Workspace, user: User) -> None:
        """
        Assign user as workspace owner (admin role)
        
        Args:
            workspace: Workspace instance
            user: User to assign as owner
        """
        admin_role = StaffRole.objects.get(workspace=workspace, code='admin')
        StaffMember.objects.create(
            workspace=workspace,
            user=user,
            role=admin_role,
            is_active=True
        )
    
    def update_workspace(self, workspace: Workspace, **kwargs: Any) -> Workspace:
        """
        Update workspace information
        
        Args:
            workspace: Workspace instance to update
            **kwargs: Fields to update
            
        Returns:
            Workspace: Updated workspace instance
        """
        self.validate_workspace_access(workspace)
        
        for key, value in kwargs.items():
            if hasattr(workspace, key):
                setattr(workspace, key, value)
        
        workspace.save()
        return workspace
    
    def deactivate_workspace(self, workspace: Workspace) -> Workspace:
        """
        Deactivate workspace
        
        Args:
            workspace: Workspace instance to deactivate
            
        Returns:
            Workspace: Updated workspace instance
        """
        self.validate_workspace_access(workspace)
        
        workspace.is_active = False
        workspace.save()
        
        return workspace

    def validate_workspace_access(self, workspace: Workspace) -> None:
        # Placeholder for access validation logic if needed
        pass

"""
BFG Permission Classes

Permission control classes
"""

from rest_framework import permissions


class IsWorkspaceAdmin(permissions.BasePermission):
    """
    Only workspace admin role can access
    """
    message = "Only workspace administrators can perform this action."
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return False
        
        # Superuser can always access
        if request.user.is_superuser:
            return True
        
        # Check if user is admin of this workspace
        from bfg.common.models import StaffMember
        try:
            staff = StaffMember.objects.get(
                workspace=workspace,
                user=request.user,
                is_active=True
            )
            return staff.role.code == 'admin'
        except StaffMember.DoesNotExist:
            return False


class IsWorkspaceStaff(permissions.BasePermission):
    """
    Any staff member of the workspace can access
    """
    message = "Only staff members can perform this action."
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return False
        
        # Superuser can always access
        if request.user.is_superuser:
            return True
        
        from bfg.common.models import StaffMember
        return StaffMember.objects.filter(
            workspace=workspace,
            user=request.user,
            is_active=True
        ).exists()


class HasPermission(permissions.BasePermission):
    """
    Check if user has specific permission
    
    Usage:
    permission_classes = [HasPermission]
    required_permission = 'shop.product.create'
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return False
        
        # Get required permission
        required_perm = getattr(view, 'required_permission', None)
        if not required_perm:
            return True
        
        # Check permission
        from bfg.common.models import StaffMember
        try:
            staff = StaffMember.objects.select_related('role').get(
                workspace=workspace,
                user=request.user,
                is_active=True
            )
            
            # Admin has all permissions
            if staff.role.code == 'admin':
                return True
            
            # Parse permission 'shop.product.create' -> module: 'shop.product', action: 'create'
            parts = required_perm.split('.')
            if len(parts) < 3:
                return False
            
            module = '.'.join(parts[:-1])
            action = parts[-1]
            
            # Check role permissions JSON
            role_perms = staff.role.permissions
            
            if module in role_perms:
                return action in role_perms[module]
            
            # Check wildcard
            if '*' in role_perms:
                return action in role_perms['*']
            
            return False
            
        except StaffMember.DoesNotExist:
            return False


class IsOwnerOrStaff(permissions.BasePermission):
    """
    Object owner or staff can access
    Used for customers accessing their own data
    """
    
    def has_object_permission(self, request, view, obj):
        workspace = getattr(request, 'workspace', None)
        
        # Staff can access
        from bfg.common.models import StaffMember
        if StaffMember.objects.filter(
            workspace=workspace,
            user=request.user,
            is_active=True
        ).exists():
            return True
        
        # Check if is owner
        if hasattr(obj, 'customer'):
            return obj.customer.user == request.user
        elif hasattr(obj, 'user'):
            return obj.user == request.user
        
        return False


class CanManagePayments(permissions.BasePermission):
    """
    Check if user has permission to manage payments.
    
    Uses permission-based checking instead of role codes for flexibility.
    Default roles should have 'finance.payment.create' permission set during initialization.
    
    Required permission: finance.payment.create (for create action)
                        finance.payment.view (for list/retrieve)
    """
    message = "You don't have permission to manage payments."
    
    # Permission mapping by action
    ACTION_PERMISSIONS = {
        'create': 'finance.payment.create',
        'update': 'finance.payment.update',
        'partial_update': 'finance.payment.update',
        'destroy': 'finance.payment.delete',
        'list': 'finance.payment.view',
        'retrieve': 'finance.payment.view',
    }
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return False
        
        # Superuser can always access
        if request.user.is_superuser:
            return True
        
        # Get the required permission for this action
        action = getattr(view, 'action', None)
        required_perm = self.ACTION_PERMISSIONS.get(action, 'finance.payment.view')
        
        # Check staff member and their role permissions
        from bfg.common.models import StaffMember
        try:
            staff = StaffMember.objects.select_related('role').get(
                workspace=workspace,
                user=request.user,
                is_active=True
            )
            
            # Admin role has all permissions
            if staff.role.code == 'admin':
                return True
            
            # Check role permissions JSON
            # Format: {"finance.payment": ["create", "view", "update", "delete"]}
            role_perms = staff.role.permissions or {}
            
            # Parse permission 'finance.payment.create' -> module: 'finance.payment', action: 'create'
            parts = required_perm.rsplit('.', 1)
            if len(parts) != 2:
                return False
            
            module, action_name = parts
            
            # Check if module exists and action is allowed
            if module in role_perms:
                module_actions = role_perms[module]
                if isinstance(module_actions, list):
                    return action_name in module_actions
                elif isinstance(module_actions, bool):
                    return module_actions
            
            # Check wildcard permission
            if '*' in role_perms:
                return True
            
            return False
            
        except StaffMember.DoesNotExist:
            return False


class CanManageInvoices(permissions.BasePermission):
    """
    Check if user has permission to manage invoices.
    
    Uses permission-based checking for flexibility.
    Required permission: finance.invoice.create/view/update/delete
    """
    message = "You don't have permission to manage invoices."
    
    ACTION_PERMISSIONS = {
        'create': 'finance.invoice.create',
        'update': 'finance.invoice.update',
        'partial_update': 'finance.invoice.update',
        'destroy': 'finance.invoice.delete',
        'list': 'finance.invoice.view',
        'retrieve': 'finance.invoice.view',
        'send': 'finance.invoice.update',
    }
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return False
        
        # Superuser can always access
        if request.user.is_superuser:
            return True
        
        # Get the required permission for this action
        action = getattr(view, 'action', None)
        required_perm = self.ACTION_PERMISSIONS.get(action, 'finance.invoice.view')
        
        from bfg.common.models import StaffMember
        try:
            staff = StaffMember.objects.select_related('role').get(
                workspace=workspace,
                user=request.user,
                is_active=True
            )
            
            # Admin role has all permissions
            if staff.role.code == 'admin':
                return True
            
            role_perms = staff.role.permissions or {}
            
            parts = required_perm.rsplit('.', 1)
            if len(parts) != 2:
                return False
            
            module, action_name = parts
            
            if module in role_perms:
                module_actions = role_perms[module]
                if isinstance(module_actions, list):
                    return action_name in module_actions
                elif isinstance(module_actions, bool):
                    return module_actions
            
            if '*' in role_perms:
                return True
            
            return False
            
        except StaffMember.DoesNotExist:
            return False

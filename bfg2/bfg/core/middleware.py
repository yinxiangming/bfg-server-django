"""
BFG Middleware

Middleware classes
"""

from django.utils.deprecation import MiddlewareMixin
from bfg.core.exceptions import PermissionDenied


class WorkspaceMiddleware(MiddlewareMixin):
    """
    Automatically identify and set current request's workspace
    
    Gets workspace ID from X-Workspace-ID request header
    """
    
    def process_request(self, request):
        from django.conf import settings
        from bfg.common.models import Workspace
        
        # Get workspace ID from request header
        workspace_id = request.headers.get('X-Workspace-ID')
        
        if workspace_id:
            try:
                workspace = Workspace.objects.get(id=workspace_id, is_active=True)
                request.workspace = workspace
                
                # Validate user belongs to this workspace
                if request.user.is_authenticated:
                    self._validate_user_workspace_access(request, workspace)
                
            except Workspace.DoesNotExist:
                request.workspace = None
        else:
            # In development mode, use default workspace if available
            if getattr(settings, 'DEBUG', False):
                request.workspace = Workspace.objects.filter(is_active=True).first()
            else:
                request.workspace = None
    
    def _validate_user_workspace_access(self, request, workspace):
        """Validate user can access this workspace"""
        user = request.user
        
        # Superuser can always access
        if user.is_superuser:
            request.is_staff_member = True
            request.is_customer = False
            return
            
        from django.core.cache import cache
        from bfg.common.models import StaffMember, Customer
        
        # Cache key for user access to workspace
        cache_key = f"user_ws_access:{user.id}:{workspace.id}"
        access_status = cache.get(cache_key)
        
        if access_status is None:
            # Check if is Staff
            is_staff = StaffMember.objects.filter(
                workspace=workspace,
                user=user,
                is_active=True
            ).exists()
            
            # Check if is Customer
            is_customer = Customer.objects.filter(
                workspace=workspace,
                user=user,
                is_active=True
            ).exists()
            
            if not (is_staff or is_customer):
                raise PermissionDenied("You do not have access to this workspace")
                
            access_status = {
                'is_staff_member': is_staff,
                'is_customer': is_customer
            }
            # Cache for 10 minutes
            cache.set(cache_key, access_status, 600)
        
        # Set user role information from cache or DB
        request.is_staff_member = access_status['is_staff_member']
        request.is_customer = access_status['is_customer']

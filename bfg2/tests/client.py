"""
Custom test client that adds workspace to requests
"""
from rest_framework.test import APIClient


class WorkspaceAPIClient(APIClient):
    """
    Custom API Client that adds workspace to request
    """
    def __init__(self, workspace=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
    
    def request(self, **kwargs):
        """Override request to add workspace"""
        response = super().request(**kwargs)
        # Add workspace to request object after it's created
        if self.workspace and hasattr(response, 'wsgi_request'):
            response.wsgi_request.workspace = self.workspace
        return response
    
    def generic(self, method, path, data='', content_type='application/octet-stream', secure=False, **extra):
        """Override generic to inject workspace into view"""
        # Store workspace for middleware simulation
        if self.workspace:
            extra['HTTP_X_WORKSPACE_ID'] = str(self.workspace.id)
            extra['HTTP_X_WORKSPACE_SLUG'] = self.workspace.slug
        
        response = super().generic(method, path, data, content_type, secure, **extra)
        
        # Inject workspace into the request for permission checks
        if self.workspace and hasattr(response, 'wsgi_request'):
            response.wsgi_request.workspace = self.workspace
            response.wsgi_request.is_staff_member = True  # Set based on user's staff membership
        
        return response

"""
E2E Test 01: User & Workspace Registration
"""

import pytest
from bfg.common.models import Workspace, User
from bfg.common.services import WorkspaceService, CustomerService

@pytest.mark.e2e
@pytest.mark.django_db
class TestRegistration:
    
    def test_workspace_creation(self, api_client):
        """Test workspace creation via API"""
        # Usually workspace creation is a superadmin task or public signup
        # Here we assume a public signup or unauthenticated endpoint for simplicity
        # or we mock a superuser. For now, let's assume we are testing the Model/Service
        # via API if exposed, but WorkspaceViewSet might be restricted.
        # Let's assume we have a superuser.
        
        # Create superuser for workspace creation
        superuser = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        api_client.force_authenticate(user=superuser)
        
        payload = {
            "name": "Test Workspace",
            "slug": "test-workspace",
            "domain": "test.com",
            "email": "admin@test.com"
        }
        
        response = api_client.post('/api/v1/workspaces/', payload)
        
        assert response.status_code == 201
        assert response.data['name'] == "Test Workspace"
        assert Workspace.objects.count() == 1
        
    def test_customer_registration(self, authenticated_client, workspace, user):
        """Test customer registration via API (Staff creates customer)"""
        # Staff user (from authenticated_client) creates a customer profile
        
        payload = {
            "user": user.id,  # Link to existing user
            "company_name": "Test Company",
            "tax_number": "TAX123"
        }
        
        response = authenticated_client.post('/api/v1/customers/', payload)
        
        assert response.status_code == 201
        assert response.data['user']['id'] == user.id
        assert response.data['workspace'] == workspace.id
        
    def test_address_creation(self, authenticated_client, workspace, customer):
        """Test address creation via API"""
        payload = {
            "full_name": "John Doe",
            "phone": "1234567890",
            "address_line1": "123 Main St",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US"
        }
        
        response = authenticated_client.post('/api/v1/addresses/', payload)
        
        assert response.status_code == 201
        assert response.data['city'] == "New York"

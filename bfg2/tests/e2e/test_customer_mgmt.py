"""
E2E Test: Customer Management
"""

import pytest
from decimal import Decimal

@pytest.mark.e2e
@pytest.mark.django_db
class TestCustomerManagement:
    
    def test_customer_segment_creation(self, authenticated_client, workspace):
        """Test customer segment creation via API"""
        response = authenticated_client.post('/api/v1/customer-segments/', {
            'name': 'VIP Customers',
            'description': 'High value customers'
        })
        
        assert response.status_code == 201
        assert response.data['name'] == 'VIP Customers'
    
    def test_customer_tag_management(self, authenticated_client, workspace):
        """Test customer tag creation and listing via API"""
        # Create first tag
        tag1_res = authenticated_client.post('/api/v1/customer-tags/', {
            'name': 'Premium'
        })
        assert tag1_res.status_code == 201
        assert tag1_res.data['name'] == 'Premium'
        
        # Create second tag  
        tag2_res = authenticated_client.post('/api/v1/customer-tags/', {
            'name': 'Wholesale'
        })
        assert tag2_res.status_code == 201
        
        # List all tags
        list_res = authenticated_client.get('/api/v1/customer-tags/')
        assert list_res.status_code == 200
        assert len(list_res.data) >= 2

"""
E2E Test 06: Warehouse Setup
"""

import pytest

@pytest.mark.e2e
@pytest.mark.django_db
class TestWarehouseSetup:
    
    def test_warehouse_configuration(self, authenticated_client, workspace):
        """Test warehouse configuration via API"""
        # 1. Create Warehouse
        wh_payload = {
            "name": "Distribution Center",
            "code": "DC-001",
            "is_active": True
        }
        
        response = authenticated_client.post('/api/v1/delivery/warehouses/', wh_payload)
        
        assert response.status_code == 201
        assert response.data['code'] == "DC-001"
        wh_id = response.data['id']
        
        # 2. Update Warehouse (e.g. add address or change settings)
        update_payload = {
            "name": "Main Distribution Center"
        }
        
        patch_res = authenticated_client.patch(f'/api/v1/delivery/warehouses/{wh_id}/', update_payload)
        
        assert patch_res.status_code == 200
        assert patch_res.data['name'] == "Main Distribution Center"
        
    def test_inventory_check(self, authenticated_client, workspace):
        """Test inventory endpoints (if exposed via warehouse API)"""
        # This assumes we have an endpoint to check stock or it's part of product API
        # For now, we just verify warehouse exists and is active
        wh_payload = {"name": "Stock WH", "code": "WH-STOCK"}
        res = authenticated_client.post('/api/v1/delivery/warehouses/', wh_payload)
        assert res.status_code == 201
        assert res.data['is_active'] is True

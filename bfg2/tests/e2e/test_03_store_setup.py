"""
E2E Test 03: Store Setup
"""

import pytest
from bfg.shop.models import Store
from bfg.shop.services import StoreService
from bfg.delivery.models import Warehouse

@pytest.mark.e2e
@pytest.mark.django_db
class TestStoreSetup:
    
    def test_warehouse_creation(self, authenticated_client, workspace):
        """Test warehouse creation via API"""
        payload = {
            "name": "Main Warehouse",
            "code": "WH-001",
            # Address is usually required or nested, assuming simplified for now or optional
            # If address is required, we might need to create it first or pass nested data
            # Let's assume basic fields for now
        }
        
        response = authenticated_client.post('/api/v1/delivery/warehouses/', payload)
        
        assert response.status_code == 201
        assert response.data['code'] == "WH-001"
        
    def test_store_creation(self, authenticated_client, workspace):
        """Test store creation via API"""
        # 1. Create warehouse
        wh_payload = {"name": "Main Warehouse", "code": "WH-001"}
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', wh_payload)
        wh_id = wh_res.data['id']
        
        # 2. Create store (use warehouse_ids instead of warehouses)
        store_payload = {
            "name": "Online Store",
            "code": "online-store",
            "description": "Our main online store",
            "warehouse_ids": [wh_id]  # Use warehouse_ids for write
        }
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', store_payload)
        
        assert store_res.status_code == 201
        assert store_res.data['code'] == "online-store"
        # warehouses is a list of objects, check if warehouse ID is in the list
        warehouse_ids = [w.get('id') for w in store_res.data.get('warehouses', [])]
        assert wh_id in warehouse_ids, f"Warehouse {wh_id} not found in {warehouse_ids}. Response: {store_res.data}"

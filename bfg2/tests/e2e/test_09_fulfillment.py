"""
E2E Test 09: Fulfillment (API-only; same contract for all backends).
"""

import pytest
from decimal import Decimal
import uuid


@pytest.mark.e2e
@pytest.mark.django_db
class TestFulfillment:
    
    def test_create_consignment(self, authenticated_client, workspace):
        """Test consignment creation via API. Uses carrier/service from API when available."""
        suffix = uuid.uuid4().hex[:6]
        # Setup: Create order with packages first
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": f"WH {suffix}", "code": f"WH-001-{suffix}", "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": f"Store {suffix}", "code": f"ST-001-{suffix}", "warehouse_ids": [wh_id]
        })
        store_id = store_res.data['id']
        
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Test Category {suffix}", "slug": f"test-category-{suffix}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"Test Product {suffix}", "slug": f"test-product-{suffix}", "price": "100.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False
        })
        prod_id = prod_res.data['id']
        
        authenticated_client.post('/api/v1/shop/carts/', {})
        authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "quantity": 1
        })
        
        recipient_res = authenticated_client.post('/api/v1/addresses/', {
            'full_name': 'John Doe',
            'phone': '0987654321',
            'address_line1': '123 Main St',
            'city': 'City',
            'state': 'NY',
            'country': 'US',
            'postal_code': '12345'
        })
        assert recipient_res.status_code == 201
        recipient_address_id = recipient_res.data['id']
        
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', {
            "store": store_id, "shipping_address": recipient_address_id, "billing_address": recipient_address_id
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']

        # Create FreightStatus before order-packages (Node requires it)
        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": f"draft-{suffix}",
            "name": f"Draft {suffix}",
            "type": "consignment",
            "state": "PENDING",
            "is_active": True
        })
        assert status_res.status_code == 201
        freight_status_id = status_res.data['id']

        package_payload = {
            'order': order_id,
            'freight_status': freight_status_id,
            'length': 30.00,
            'width': 20.00,
            'height': 15.00,
            'weight': 2.50,
            'pieces': 1,
            'quantity': 1,
            'description': 'Test package'
        }
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', package_payload)
        assert package_res.status_code == 201

        # Create sender address via API
        sender_res = authenticated_client.post('/api/v1/addresses/', {
            'full_name': 'Sender Name',
            'phone': '1234567890',
            'address_line1': '123 Sender St',
            'city': 'City',
            'state': 'CA',
            'country': 'US',
            'postal_code': '12345'
        })
        assert sender_res.status_code == 201
        sender_address_id = sender_res.data['id']

        payload = {"order_ids": [order_id], "status_id": freight_status_id}
        carrier_res = authenticated_client.post('/api/v1/delivery/carriers/', {
            "name": f"Carrier {suffix}", "code": f"CR-{suffix}", "is_active": True
        })
        if carrier_res.status_code == 201:
            service_res = authenticated_client.post('/api/v1/delivery/freight-services/', {
                "carrier": carrier_res.data['id'],
                "name": f"Service {suffix}", "code": f"SVC-{suffix}",
                "base_price": "10.00", "price_per_kg": "5.00", "is_active": True
            })
            if service_res.status_code == 201:
                payload["service_id"] = service_res.data['id']
                payload["sender_address_id"] = sender_address_id
                payload["recipient_address_id"] = recipient_address_id
                payload["state"] = "PENDING"

        response = authenticated_client.post('/api/v1/delivery/consignments/', payload)
        assert response.status_code == 201
        # Python returns state, Node returns status
        if 'state' in response.data:
            assert response.data['state'] == "PENDING"
        else:
            assert response.data.get('status') in ('pending', 'PENDING', None)
        
    def test_update_tracking(self, authenticated_client, workspace):
        """Test updating tracking info. Skips if carrier/service or PATCH consignment not implemented."""
        suffix = uuid.uuid4().hex[:6]
        # Setup: Create order with packages first
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": f"WH {suffix}", "code": f"WH-001-{suffix}", "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": f"Store {suffix}", "code": f"ST-001-{suffix}", "warehouse_ids": [wh_id]
        })
        store_id = store_res.data['id']
        
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Test Category {suffix}", "slug": f"test-category-{suffix}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"Test Product {suffix}", "slug": f"test-product-{suffix}", "price": "100.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False
        })
        prod_id = prod_res.data['id']
        
        authenticated_client.post('/api/v1/shop/carts/', {})
        authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "quantity": 1
        })
        
        recipient_res = authenticated_client.post('/api/v1/addresses/', {
            'full_name': 'John Doe',
            'phone': '0987654321',
            'address_line1': '123 Main St',
            'city': 'City',
            'state': 'NY',
            'country': 'US',
            'postal_code': '12345'
        })
        assert recipient_res.status_code == 201
        recipient_address_id = recipient_res.data['id']
        
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', {
            "store": store_id, "shipping_address": recipient_address_id, "billing_address": recipient_address_id
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']

        # Create FreightStatus before order-packages (Node requires it)
        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": f"draft-{suffix}",
            "name": f"Draft {suffix}",
            "type": "consignment",
            "state": "PENDING",
            "is_active": True
        })
        assert status_res.status_code == 201
        freight_status_id = status_res.data['id']

        package_payload = {
            'order': order_id,
            'freight_status': freight_status_id,
            'length': 30.00,
            'width': 20.00,
            'height': 15.00,
            'weight': 2.50,
            'pieces': 1,
            'quantity': 1
        }
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', package_payload)
        assert package_res.status_code == 201

        # Create addresses via API
        sender_res = authenticated_client.post('/api/v1/addresses/', {
            'full_name': 'Sender Name',
            'phone': '1234567890',
            'address_line1': '123 Sender St',
            'city': 'City',
            'state': 'CA',
            'country': 'US',
            'postal_code': '12345'
        })
        assert sender_res.status_code == 201
        sender_address_id = sender_res.data['id']
        recipient_address_id = recipient_res.data['id']

        carrier_res = authenticated_client.post('/api/v1/delivery/carriers/', {
            "name": f"Carrier {suffix}", "code": f"CR-{suffix}", "is_active": True
        })
        assert carrier_res.status_code == 201, (
            f"delivery/carriers create failed: {carrier_res.status_code} {carrier_res.data}"
        )
        service_res = authenticated_client.post('/api/v1/delivery/freight-services/', {
            "carrier": carrier_res.data['id'],
            "name": f"Service {suffix}", "code": f"SVC-{suffix}",
            "base_price": "10.00", "price_per_kg": "5.00", "is_active": True
        })
        assert service_res.status_code == 201, (
            f"delivery/freight-services create failed: {service_res.status_code} {service_res.data}"
        )

        con_res = authenticated_client.post('/api/v1/delivery/consignments/', {
            "service_id": service_res.data['id'],
            "sender_address_id": sender_address_id,
            "recipient_address_id": recipient_address_id,
            "status_id": freight_status_id,
            "state": "PENDING",
            "order_ids": [order_id]
        })
        assert con_res.status_code == 201
        con_number = con_res.data.get('consignment_number') or con_res.data.get('id')

        # Update Tracking via API
        payload = {
            "tracking_number": "TRACK123"
        }
        
        res = authenticated_client.patch(f'/api/v1/delivery/consignments/{con_number}/', payload)
        assert res.status_code == 200, (
            f"PATCH consignment failed: {res.status_code} {res.data}"
        )
        assert res.data.get('tracking_number') == "TRACK123"

    def test_return_workflow(self, authenticated_client, workspace):
        """Test return workflow endpoint. Skips if not implemented (404)."""
        list_res = authenticated_client.get('/api/v1/shop/returns/')
        assert list_res.status_code == 200, (
            f"shop/returns list failed: {list_res.status_code} {list_res.data}"
        )
    
    def test_package_template_management(self, authenticated_client, workspace):
        """Test package template creation and management via API"""
        suffix = uuid.uuid4().hex[:6]
        template_code = f"A4-{suffix}"
        # Create package template
        create_res = authenticated_client.post('/api/v1/delivery/package-templates/', {
            'code': template_code,
            'name': f'A4 Box {suffix}',
            'description': 'Standard A4 size box',
            'length': '30.00',
            'width': '20.00',
            'height': '15.00',
            'tare_weight': '0.10',
            'max_weight': '10.00',
            'order': 1,
            'is_active': True
        })
        assert create_res.status_code == 201
        template_id = create_res.data['id']
        assert create_res.data['code'] == template_code
        assert 'A4 Box' in create_res.data['name']
        assert Decimal(str(create_res.data['length'])) == Decimal('30.00')
        if 'volume_cm3' in create_res.data:
            assert create_res.data['volume_cm3'] is not None

        # Get template
        get_res = authenticated_client.get(f'/api/v1/delivery/package-templates/{template_id}/')
        assert get_res.status_code == 200
        assert get_res.data['id'] == template_id
        
        # Update template
        update_res = authenticated_client.patch(f'/api/v1/delivery/package-templates/{template_id}/', {
            'name': 'A4 Box Updated',
            'description': 'Updated description'
        })
        assert update_res.status_code == 200
        assert update_res.data['name'] == 'A4 Box Updated'
        
        # List templates
        list_res = authenticated_client.get('/api/v1/delivery/package-templates/')
        assert list_res.status_code == 200
        if isinstance(list_res.data, list):
            templates = list_res.data
        else:
            templates = list_res.data.get('results', [])
        assert len(templates) >= 1
    
    def test_order_packages_with_fulfillment(self, authenticated_client, workspace):
        """Test order packages creation and shipping calculation. Skips freight steps if not implemented (404)."""
        suffix = uuid.uuid4().hex[:6]
        # Setup: Create order via checkout flow
        # Create warehouse
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": f"Main WH {suffix}", "code": f"WH-MAIN-{suffix}", "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        # Create store
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": f"Test Store {suffix}", "code": f"STORE-001-{suffix}", "warehouse_ids": [wh_id]
        })
        store_id = store_res.data['id']
        
        # Create category and product
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Test Category {suffix}", "slug": f"test-category-{suffix}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"Test Product {suffix}", "slug": f"test-product-{suffix}", "price": "100.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False
        })
        prod_id = prod_res.data['id']
        
        # Create cart and checkout
        authenticated_client.post('/api/v1/shop/carts/', {})
        authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "quantity": 1
        })
        
        addr_res = authenticated_client.post('/api/v1/addresses/', {
            "full_name": "John Doe", "phone": "1234567890",
            "address_line1": "123 Main St", "city": "City", "country": "US", "postal_code": "12345"
        })
        address_id = addr_res.data['id']
        
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', {
            "store": store_id, "shipping_address": address_id, "billing_address": address_id
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']
        
        # Create package template
        template_res = authenticated_client.post('/api/v1/delivery/package-templates/', {
            'code': f'TEST-{suffix}', 'name': f'Test Box {suffix}', 'length': '30.00', 'width': '20.00',
            'height': '15.00', 'tare_weight': '0.10', 'is_active': True
        })
        template_id = template_res.data['id']

        # Create FreightStatus before order-packages (Node requires it)
        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": f"draft-{suffix}",
            "name": f"Draft {suffix}",
            "type": "consignment",
            "state": "PENDING",
            "is_active": True
        })
        assert status_res.status_code == 201
        freight_status_id = status_res.data['id']
        
        package_payload = {
            'order': order_id,
            'template': template_id,
            'freight_status': freight_status_id,
            'weight': 2.50,
            'pieces': 1,
            'quantity': 1,
            'description': 'Test package'
        }
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', package_payload)
        assert package_res.status_code == 201
        order_val = package_res.data.get('order') or package_res.data.get('order_id')
        assert order_val == order_id
        template_val = package_res.data.get('template') or package_res.data.get('template_id')
        if isinstance(template_val, dict):
            assert template_val.get('id') == template_id
        else:
            assert template_val == template_id
        if 'weight' in package_res.data:
            assert Decimal(str(package_res.data['weight'])) == Decimal('2.50')
        if 'billing_weight' in package_res.data:
            assert package_res.data['billing_weight'] is not None
        if 'volumetric_weight' in package_res.data:
            assert package_res.data['volumetric_weight'] is not None

        carrier_res = authenticated_client.post('/api/v1/delivery/carriers/', {
            "name": f"Test Carrier {suffix}", "code": f"TC-001-{suffix}", "is_active": True
        })
        assert carrier_res.status_code == 201, (
            f"delivery/carriers create failed: {carrier_res.status_code} {carrier_res.data}"
        )
        carrier_id = carrier_res.data['id']

        service_res = authenticated_client.post('/api/v1/delivery/freight-services/', {
            "carrier": carrier_id,
            "name": f"Standard Shipping {suffix}",
            "code": f"STD-{suffix}",
            "base_price": "10.00",
            "price_per_kg": "5.00",
            "is_active": True
        })
        assert service_res.status_code == 201, (
            f"delivery/freight-services create failed: {service_res.status_code} {service_res.data}"
        )
        service_id = service_res.data['id']

        # Calculate shipping cost
        calc_res = authenticated_client.post('/api/v1/shop/order-packages/calculate_shipping/', {
            'order': order_id,
            'freight_service_id': service_id
        })
        assert calc_res.status_code == 200
        assert 'total_packages' in calc_res.data
        assert 'total_billing_weight' in calc_res.data
        assert 'shipping_cost' in calc_res.data
        assert calc_res.data['total_packages'] == 1
        
        # Update order shipping cost
        update_shipping_res = authenticated_client.post('/api/v1/shop/order-packages/update_order_shipping/', {
            'order': order_id,
            'freight_service_id': service_id
        })
        assert update_shipping_res.status_code == 200
        assert update_shipping_res.data['order_id'] == order_id
        assert 'shipping_cost' in update_shipping_res.data
        
        # Verify order detail includes packages
        order_detail_res = authenticated_client.get(f'/api/v1/shop/orders/{order_id}/')
        assert order_detail_res.status_code == 200
        assert 'packages' in order_detail_res.data
        assert isinstance(order_detail_res.data['packages'], list)
        assert len(order_detail_res.data['packages']) == 1
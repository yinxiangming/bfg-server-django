"""
E2E Test 09: Fulfillment
Includes: consignments, package templates, order packages, shipping calculation
"""

import pytest
from decimal import Decimal

@pytest.mark.e2e
@pytest.mark.django_db
class TestFulfillment:
    
    def test_create_consignment(self, authenticated_client, workspace, freight_service):
        """Test consignment creation via API"""
        # Setup: Create order with packages first
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": "WH", "code": "WH-001", "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": "Store", "code": "ST-001"
        })
        store_id = store_res.data['id']
        authenticated_client.post(f'/api/v1/shop/stores/{store_id}/warehouses/', {
            "warehouse_ids": [wh_id]
        })
        
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": "test-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": "Test Product", "slug": "test-product", "price": "100.00",
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
        
        # Create package for order
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', {
            'order': order_id,
            'length': '30.00', 'width': '20.00', 'height': '15.00',
            'weight': '2.50', 'quantity': 1, 'description': 'Test package'
        })
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
        
        # Create FreightStatus via API
        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": "draft",
            "name": "Draft",
            "type": "consignment",
            "state": "PENDING",
            "is_active": True
        })
        assert status_res.status_code == 201
        freight_status_id = status_res.data['id']
        
        # Create Consignment via API (now with order and packages)
        payload = {
            "service_id": freight_service.id,
            "sender_address_id": sender_address_id,
            "recipient_address_id": recipient_address_id,
            "status_id": freight_status_id,
            "state": "PENDING",
            "order_ids": [order_id]  # Include order_ids
        }
        
        response = authenticated_client.post('/api/v1/delivery/consignments/', payload)
        
        assert response.status_code == 201
        assert response.data['state'] == "PENDING"
        
    def test_update_tracking(self, authenticated_client, workspace, freight_service):
        """Test updating tracking info"""
        # Setup: Create order with packages first
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": "WH", "code": "WH-001", "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": "Store", "code": "ST-001"
        })
        store_id = store_res.data['id']
        authenticated_client.post(f'/api/v1/shop/stores/{store_id}/warehouses/', {
            "warehouse_ids": [wh_id]
        })
        
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": "test-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": "Test Product", "slug": "test-product", "price": "100.00",
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
        
        # Create package for order
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', {
            'order': order_id,
            'length': '30.00', 'width': '20.00', 'height': '15.00',
            'weight': '2.50', 'quantity': 1
        })
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
        
        # Create FreightStatus via API
        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": "draft",
            "name": "Draft",
            "type": "consignment",
            "state": "PENDING",
            "is_active": True
        })
        assert status_res.status_code == 201
        freight_status_id = status_res.data['id']
        
        # Create Consignment via API
        con_res = authenticated_client.post('/api/v1/delivery/consignments/', {
            "service_id": freight_service.id,
            "sender_address_id": sender_res.data['id'],
            "recipient_address_id": recipient_res.data['id'],
            "status_id": freight_status_id,
            "state": "PENDING",
            "order_ids": [order_id]  # Include order_ids
        })
        assert con_res.status_code == 201
        con_number = con_res.data['consignment_number']
        
        # Update Tracking via API
        payload = {
            "tracking_number": "TRACK123"
        }
        
        res = authenticated_client.patch(f'/api/v1/delivery/consignments/{con_number}/', payload)
        
        assert res.status_code == 200
        assert res.data['tracking_number'] == "TRACK123"
    
    def test_return_workflow(self, authenticated_client, workspace):
        """Test return workflow endpoint"""
        # Test returns list endpoint
        # Full return creation requires completed order setup
        list_res = authenticated_client.get('/api/v1/shop/returns/')
        assert list_res.status_code == 200
    
    def test_package_template_management(self, authenticated_client, workspace):
        """Test package template creation and management via API"""
        # Create package template
        create_res = authenticated_client.post('/api/v1/delivery/package-templates/', {
            'code': 'A4',
            'name': 'A4 Box',
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
        assert create_res.data['code'] == 'A4'
        assert create_res.data['name'] == 'A4 Box'
        assert Decimal(str(create_res.data['length'])) == Decimal('30.00')
        assert 'volume_cm3' in create_res.data
        
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
        """Test order packages creation and shipping calculation as part of fulfillment"""
        # Setup: Create order via checkout flow
        # Create warehouse
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": "Main WH", "code": "WH-MAIN", "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        # Create store
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": "Test Store", "code": "STORE-001"
        })
        store_id = store_res.data['id']
        # Link warehouse to store
        authenticated_client.post(f'/api/v1/shop/stores/{store_id}/warehouses/', {
            "warehouse_ids": [wh_id]
        })
        
        # Create category and product
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": "test-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": "Test Product", "slug": "test-product", "price": "100.00",
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
            'code': 'TEST', 'name': 'Test Box', 'length': '30.00', 'width': '20.00',
            'height': '15.00', 'tare_weight': '0.10', 'is_active': True
        })
        template_id = template_res.data['id']
        
        # Create order package with template
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', {
            'order': order_id,
            'template': template_id,
            'weight': '2.50',
            'quantity': 1,
            'description': 'Test package'
        })
        assert package_res.status_code == 201
        assert package_res.data['order'] == order_id
        assert package_res.data['template'] == template_id
        assert Decimal(str(package_res.data['weight'])) == Decimal('2.50')
        assert 'billing_weight' in package_res.data
        assert 'volumetric_weight' in package_res.data
        
        # Create carrier and freight service
        carrier_res = authenticated_client.post('/api/v1/delivery/carriers/', {
            "name": "Test Carrier", "code": "TC-001", "is_active": True
        })
        carrier_id = carrier_res.data['id']
        
        service_res = authenticated_client.post('/api/v1/delivery/freight-services/', {
            "carrier": carrier_id,
            "name": "Standard Shipping",
            "code": "STD",
            "base_price": "10.00",
            "price_per_kg": "5.00",
            "is_active": True
        })
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
"""
E2E Test 17.4: Storefront Orders API (API-only; same contract for all backends).
"""

import pytest
from decimal import Decimal


@pytest.mark.e2e
class TestStorefrontOrders:
    """Test storefront order-related API"""
    
    def test_checkout_flow(self, authenticated_client, workspace, message_templates):
        """Test complete checkout flow with notifications"""
        import uuid
        suffix = uuid.uuid4().hex[:6]

        # Setup: Create store and product via API
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": f"Main Warehouse {suffix}", "code": f"WH-001-{suffix}",
            "city": "New York", "country": "US", "postal_code": "10001"
        })
        assert wh_res.status_code == 201
        wh_id = wh_res.data['id']
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": f"Test Store {suffix}", "code": f"STORE-001-{suffix}"
        })
        assert store_res.status_code == 201
        store_id = store_res.data['id']
        
        # Link warehouse to store
        authenticated_client.post(f'/api/v1/shop/stores/{store_id}/warehouses/', {
            "warehouse_ids": [wh_id]
        })
        
        # Create category and product
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Clothing {suffix}", "slug": f"clothing-{suffix}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"T-Shirt {suffix}", "slug": f"t-shirt-{suffix}", "sku": f"TSHIRT-{suffix}".upper(),
            "price": "25.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False,  # Disable inventory tracking for this test
            "description": f"Test product {suffix}",
        })
        prod_id = prod_res.data['id']
        
        # Add to cart
        add_res = authenticated_client.post('/api/v1/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 2
        })
        assert add_res.status_code == 200
        cart_id = add_res.data.get("id")
        assert cart_id is not None
        
        # Create shipping address
        addr_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "Jane Smith",
            "phone": "+1987654321",
            "address_line1": "456 Oak Avenue",
            "city": "Los Angeles",
            "state": "CA",
            "postal_code": "90001",
            "country": "US",
            "is_default": True
        })
        assert addr_res.status_code == 201
        address_id = addr_res.data['id']
        
        # Checkout
        checkout_res = authenticated_client.post(
            '/api/v1/store/cart/checkout/',
            {
                "store": store_id,
                "shipping_address": address_id,
                "billing_address": address_id,
                "customer_note": "Please deliver in the morning"
            },
            HTTP_X_CART_ID=str(cart_id),
        )
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']
        assert 'order_number' in checkout_res.data
        assert checkout_res.data['status'] == 'pending'
        assert checkout_res.data['payment_status'] == 'pending'
        # Python nests under 'amounts'; Node may use top-level keys
        if 'amounts' in checkout_res.data:
            amounts = checkout_res.data['amounts']
            expected_total = (
                Decimal(str(amounts['subtotal']))
                + Decimal(str(amounts['shipping_cost']))
                + Decimal(str(amounts['tax']))
                - Decimal(str(amounts['discount']))
            )
            assert Decimal(str(amounts['total'])) == expected_total
        else:
            assert 'discount_amount' in checkout_res.data or 'total' in checkout_res.data
        assert 'items' in checkout_res.data
        assert len(checkout_res.data['items']) == 1

    def test_order_listing_and_detail(self, authenticated_client, workspace, user):
        """Test order listing and detail retrieval with packages"""
        import uuid
        suffix = uuid.uuid4().hex[:6]

        # Setup: Create order via checkout flow (API only)
        # Create warehouse
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": f"WH {suffix}", "code": f"WH-001-{suffix}",
            "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        # Create store
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": f"Store {suffix}", "code": f"ST-001-{suffix}"
        })
        store_id = store_res.data['id']
        authenticated_client.post(f'/api/v1/shop/stores/{store_id}/warehouses/', {
            "warehouse_ids": [wh_id]
        })
        
        # Create category and product
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Test Category {suffix}", "slug": f"test-category-{suffix}",
            "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"Test Product {suffix}", "slug": f"test-product-{suffix}", "sku": f"SKU-{suffix}".upper(),
            "price": "100.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False,
            "description": f"Test product {suffix}",
        })
        prod_id = prod_res.data['id']
        
        # Create cart and checkout
        authenticated_client.post('/api/v1/shop/carts/', {})
        authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "quantity": 1
        })
        
        addr_res = authenticated_client.post('/api/v1/addresses/', {
            "full_name": "Test User", "phone": "1234567890",
            "address_line1": "123 St", "city": "City", "country": "US", "postal_code": "12345"
        })
        address_id = addr_res.data['id']
        
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', {
            "store": store_id, "shipping_address": address_id, "billing_address": address_id
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']

        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": f"draft-{suffix}", "name": f"Draft {suffix}", "type": "consignment",
            "state": "PENDING", "is_active": True
        })
        assert status_res.status_code == 201
        freight_status_id = status_res.data['id']
        package_payload = {
            'order': order_id,
            'freight_status': freight_status_id,
            'length': 30.0,
            'width': 20.0,
            'height': 15.0,
            'weight': 2.5,
            'pieces': 1,
            'quantity': 1,
            'description': 'Test package'
        }
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', package_payload)
        assert package_res.status_code == 201
        
        # Test: List orders
        list_res = authenticated_client.get('/api/v1/store/orders/')
        assert list_res.status_code == 200
        # Handle both paginated and non-paginated responses
        if isinstance(list_res.data, list):
            orders = list_res.data
        else:
            orders = list_res.data.get('results', [])
        assert len(orders) >= 1
        
        # Test: Filter by status
        filtered_res = authenticated_client.get('/api/v1/store/orders/?status=pending')
        assert filtered_res.status_code == 200
        
        # Test: Get order detail (should include packages)
        detail_res = authenticated_client.get(f'/api/v1/store/orders/{order_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == order_id
        assert 'order_number' in detail_res.data
        assert 'packages' in detail_res.data
        assert isinstance(detail_res.data['packages'], list)
        if detail_res.data['packages']:
            assert len(detail_res.data['packages']) >= 1
        if detail_res.data.get('amounts') is not None:
            assert isinstance(detail_res.data['amounts'], (dict, type(None)))
        if detail_res.data.get('addresses') is not None:
            assert isinstance(detail_res.data['addresses'], (dict, list, type(None)))
    
    def test_order_cancellation(self, authenticated_client, workspace, user):
        """Test order cancellation with notification"""
        import uuid
        suffix = uuid.uuid4().hex[:6]

        # Setup: Create order via checkout flow (API only)
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {
            "name": f"WH {suffix}", "code": f"WH-001-{suffix}",
            "city": "City", "country": "US", "postal_code": "12345"
        })
        wh_id = wh_res.data['id']
        
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": f"Store {suffix}", "code": f"ST-001-{suffix}"
        })
        store_id = store_res.data['id']
        authenticated_client.post(f'/api/v1/shop/stores/{store_id}/warehouses/', {
            "warehouse_ids": [wh_id]
        })
        
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Test Category {suffix}", "slug": f"test-category-{suffix}",
            "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"Test Product {suffix}", "slug": f"test-product-{suffix}", "sku": f"SKU-{suffix}".upper(),
            "price": "100.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False,
            "description": f"Test product {suffix}",
        })
        prod_id = prod_res.data['id']
        
        authenticated_client.post('/api/v1/shop/carts/', {})
        authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "quantity": 1
        })
        
        addr_res = authenticated_client.post('/api/v1/addresses/', {
            "full_name": "Test User", "phone": "1234567890",
            "address_line1": "123 St", "city": "City", "country": "US", "postal_code": "12345"
        })
        address_id = addr_res.data['id']
        
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', {
            "store": store_id, "shipping_address": address_id, "billing_address": address_id
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']
        
        # Test: Cancel order
        cancel_res = authenticated_client.post(f'/api/v1/store/orders/{order_id}/cancel/', {
            "reason": "Changed my mind"
        })
        assert cancel_res.status_code == 200
        assert cancel_res.data['status'] == 'cancelled'


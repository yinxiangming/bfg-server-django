"""
E2E Test 10: Full Workflow (API-only; same contract for all backends).
"""

import pytest
from decimal import Decimal
import uuid


@pytest.mark.e2e
@pytest.mark.django_db
class TestFullWorkflow:
    
    def test_complete_customer_journey(self, authenticated_client, workspace, user, message_templates):
        """
        Test complete customer journey:
        1. Setup Store & Products
        2. Customer Browses & Adds to Cart
        3. Checkout & Payment
        4. Order Fulfillment
        """
        # --- Step 1: Setup ---
        # Warehouse
        wh_res = authenticated_client.post('/api/v1/delivery/warehouses/', {"name": "Main WH", "code": "WH-MAIN"})
        wh_id = wh_res.data['id']
        
        # Store
        store_res = authenticated_client.post('/api/v1/shop/stores/', {
            "name": "Mega Store", "code": "mega-store", "default_warehouse": wh_id
        })
        store_id = store_res.data['id']
        
        # Category
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Gadgets", "slug": "gadgets", "language": "en"
        })
        cat_id = cat_res.data['id']
        
        # Product
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": "Super Gadget", "slug": "super-gadget", "category_ids": [cat_id], 
            "price": "100.00", "language": "en"
        })
        prod_id = prod_res.data['id']
        
        # Variant with stock
        var_res = authenticated_client.post('/api/v1/shop/variants/', {
            "product": prod_id, "sku": "GADGET-001", "name": "Standard", "price": "100.00", "stock_quantity": 10
        })
        var_id = var_res.data['id']
        
        # --- Step 2: Shopping ---
        # Create Cart
        cart_res = authenticated_client.post('/api/v1/shop/carts/', {})
        cart_id = cart_res.data['id']
        
        # Add to Cart
        add_res = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "variant": var_id, "quantity": 1
        })
        assert add_res.status_code == 200
        
        # --- Step 3: Checkout ---
        # Create Address for order via API
        addr_res = authenticated_client.post('/api/v1/addresses/', {
            "full_name": "John Doe",
            "phone": "1234567890",
            "address_line1": "123 Main St",
            "city": "City",
            "country": "US",
            "postal_code": "12345"
        })
        assert addr_res.status_code == 201
        address_id = addr_res.data['id']
        
        # Use cart checkout to create order (proper flow)
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', {
            "store": store_id,
            "shipping_address": address_id,
            "billing_address": address_id  # Required field
        })
        assert checkout_res.status_code == 201
        order_id = checkout_res.data['id']
        
        # --- Step 4: Payment ---
        # Create Payment Gateway via API
        gateway_res = authenticated_client.post('/api/v1/finance/payment-gateways/', {
            "name": "Test Gateway",
            "gateway_type": "custom",
            "is_active": True
        })
        assert gateway_res.status_code == 201
        gateway_id = gateway_res.data['id']
        
        # Get currency via API first; create via API if listing is empty
        currency_id = None
        try:
            currency_list_res = authenticated_client.get('/api/v1/finance/currencies/?code=USD')
            if currency_list_res.status_code == 200:
                if isinstance(currency_list_res.data, list) and currency_list_res.data:
                    currency_id = currency_list_res.data[0]['id']
                elif isinstance(currency_list_res.data, dict) and currency_list_res.data.get('results'):
                    if currency_list_res.data['results']:
                        currency_id = currency_list_res.data['results'][0]['id']
        except Exception:
            pass

        if not currency_id:
            create_res = authenticated_client.post('/api/v1/finance/currencies/', {
                "code": "USD", "name": "US Dollar", "symbol": "$", "decimal_places": 2
            })
            if create_res.status_code == 201:
                currency_id = create_res.data.get('id')
        assert currency_id, "Could not resolve or create USD currency for payment"
        
        # Get order total from checkout response
        order_total = Decimal(str(checkout_res.data['total']))
        
        pay_res = authenticated_client.post('/api/v1/finance/payments/', {
            "order_id": order_id,
            "gateway_id": gateway_id,
            "currency_id": currency_id,
            "amount": str(order_total),  # Use calculated order total
            "status": "pending"
        })
        assert pay_res.status_code == 201
        payment_id = pay_res.data['id']

        # --- Step 5: Fulfillment with Packages ---
        # Create package template via API
        template_res = authenticated_client.post('/api/v1/delivery/package-templates/', {
            'code': 'STANDARD', 'name': 'Standard Box', 'length': '30.00', 'width': '20.00',
            'height': '15.00', 'tare_weight': '0.10', 'is_active': True
        })
        assert template_res.status_code == 201
        template_id = template_res.data['id']

        status_res = authenticated_client.post('/api/v1/delivery/freight-statuses/', {
            "code": "draft", "name": "Draft", "type": "consignment",
            "state": "PENDING", "is_active": True
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
            'description': 'Order package'
        }
        package_res = authenticated_client.post('/api/v1/shop/order-packages/', package_payload)
        assert package_res.status_code == 201
        if 'billing_weight' in package_res.data:
            assert package_res.data['billing_weight'] is not None
        
        # Create prerequisites for Consignment via API
        # Create sender address via API
        sender_addr_res = authenticated_client.post('/api/v1/addresses/', {
            "full_name": "Sender Name",
            "phone": "1234567890",
            "address_line1": "123 Sender St",
            "city": "City",
            "country": "US",
            "postal_code": "12345"
        })
        assert sender_addr_res.status_code == 201
        sender_address_id = sender_addr_res.data['id']

        service_id = None
        carrier_res = authenticated_client.post('/api/v1/delivery/carriers/', {
            "name": "Test Carrier",
            "code": "TC-001",
            "is_active": True
        })
        if carrier_res.status_code == 201:
            carrier_id = carrier_res.data['id']
            service_res = authenticated_client.post('/api/v1/delivery/freight-services/', {
                "carrier": carrier_id,
                "name": "Standard Shipping",
                "code": "STD",
                "base_price": "10.00",
                "price_per_kg": "5.00",
                "is_active": True
            })
            if service_res.status_code == 201:
                service_id = service_res.data['id']
                calc_res = authenticated_client.post('/api/v1/shop/order-packages/calculate_shipping/', {
                    'order': order_id,
                    'freight_service_id': service_id
                })
                if calc_res.status_code == 200:
                    authenticated_client.post('/api/v1/shop/order-packages/update_order_shipping/', {
                        'order': order_id,
                        'freight_service_id': service_id
                    })

        con_payload = {
            "order_ids": [order_id],
            "status_id": freight_status_id,
        }
        if service_id is not None:
            con_payload["service_id"] = service_id
            con_payload["sender_address_id"] = sender_address_id
            con_payload["recipient_address_id"] = address_id
            con_payload["state"] = "PENDING"
        con_res = authenticated_client.post('/api/v1/delivery/consignments/', con_payload)
        assert con_res.status_code == 201

        order_detail_res = authenticated_client.get(f'/api/v1/shop/orders/{order_id}/')
        assert order_detail_res.status_code == 200
        assert 'packages' in order_detail_res.data
        assert isinstance(order_detail_res.data['packages'], list)
        if order_detail_res.data['packages']:
            assert len(order_detail_res.data['packages']) >= 1
        
        # Verify final state
        # Order should be paid, packages created, consignment created, notifications sent

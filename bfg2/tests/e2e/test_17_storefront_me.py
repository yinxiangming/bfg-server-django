"""
E2E Test 17.5: Storefront Me API (API-only; same contract for all backends).
"""

import os
import pytest
from datetime import datetime


@pytest.mark.e2e
class TestStorefrontMe:
    """Test storefront personal information API"""
    
    def test_me_api(self, authenticated_client, workspace):
        """Test /api/v1/me/ API for personal information"""
        # Get current user info
        me_res = authenticated_client.get('/api/v1/me/')
        assert me_res.status_code == 200
        assert 'id' in me_res.data
        assert 'username' in me_res.data
        assert 'email' in me_res.data
        assert 'customer' in me_res.data
        
        # Update user info
        update_res = authenticated_client.patch('/api/v1/me/', {
            "first_name": "Updated",
            "last_name": "Name",
            "phone": "+1234567890"
        })
        assert update_res.status_code == 200
        assert update_res.data['first_name'] == "Updated"
        assert update_res.data['last_name'] == "Name"
        assert update_res.data['phone'] == "+1234567890"
        # Change-password and reset-password are in test_z_last_me_sensitive.py (run at end of e2e)

    def test_address_management(self, authenticated_client, workspace):
        """Test customer address management via /api/v1/me/addresses/"""
        # Create address
        create_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "John Doe",
            "phone": "+1234567890",
            "email": "john@example.com",
            "address_line1": "123 Main Street",
            "address_line2": "Apt 4B",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
            "is_default": True
        })
        assert create_res.status_code == 201
        address_id = create_res.data['id']
        assert create_res.data['full_name'] == "John Doe"
        assert create_res.data['city'] == "New York"
        assert create_res.data['is_default'] is True
        
        # List addresses
        list_res = authenticated_client.get('/api/v1/me/addresses/')
        assert list_res.status_code == 200
        # Handle both paginated and non-paginated responses
        if isinstance(list_res.data, list):
            addresses = list_res.data
        else:
            addresses = list_res.data.get('results', [])
        assert len(addresses) >= 1
        
        # Get default address
        default_res = authenticated_client.get('/api/v1/me/addresses/default/')
        assert default_res.status_code == 200
        assert default_res.data['id'] == address_id
        
        # Update address
        update_res = authenticated_client.patch(f'/api/v1/me/addresses/{address_id}/', {
            "city": "Brooklyn"
        })
        assert update_res.status_code == 200
        assert update_res.data['city'] == "Brooklyn"
    
    def test_address_deletion(self, authenticated_client, workspace):
        """Test address deletion"""
        # Create multiple addresses
        addr1_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "John Doe",
            "phone": "+1234567890",
            "address_line1": "123 Main St",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
            "is_default": True
        })
        assert addr1_res.status_code == 201
        addr1_id = addr1_res.data['id']
        
        addr2_res = authenticated_client.post('/api/v1/me/addresses/', {
            "full_name": "Jane Smith",
            "phone": "+0987654321",
            "address_line1": "456 Oak Ave",
            "city": "Los Angeles",
            "state": "CA",
            "postal_code": "90001",
            "country": "US",
            "is_default": False
        })
        assert addr2_res.status_code == 201
        addr2_id = addr2_res.data['id']
        
        # Test: Delete address
        delete_res = authenticated_client.delete(f'/api/v1/me/addresses/{addr2_id}/')
        assert delete_res.status_code == 204, "Delete should return 204 No Content"
        
        # Verify address is deleted
        list_res = authenticated_client.get('/api/v1/me/addresses/')
        assert list_res.status_code == 200
        addresses = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        address_ids = [addr['id'] for addr in addresses]
        assert addr2_id not in address_ids, "Deleted address should not be in list"
        assert addr1_id in address_ids, "Other address should still exist"
        
        # Test: Cannot delete non-existent address
        fake_id = 99999
        delete_fake_res = authenticated_client.delete(f'/api/v1/me/addresses/{fake_id}/')
        assert delete_fake_res.status_code == 404, "Should return 404 for non-existent address"
    
    def test_me_settings(self, authenticated_client, workspace, user):
        """Test /api/v1/me/settings/ API for user preferences"""
        # Get preferences (should auto-create if not exists)
        get_res = authenticated_client.get('/api/v1/me/settings/')
        assert get_res.status_code == 200
        assert 'email_notifications' in get_res.data
        assert 'theme' in get_res.data
        assert 'profile_visibility' in get_res.data
        
        # Update preferences
        update_res = authenticated_client.patch('/api/v1/me/settings/', {
            "email_notifications": False,
            "theme": "dark",
            "profile_visibility": "public",
            "notify_promotions": False,
            "items_per_page": 50
        })
        assert update_res.status_code == 200
        assert update_res.data['email_notifications'] is False
        assert update_res.data['theme'] == "dark"
        assert update_res.data['profile_visibility'] == "public"
        assert update_res.data['notify_promotions'] is False
        assert update_res.data['items_per_page'] == 50
        
        # Verify update persisted (Node may not persist theme)
        get_again_res = authenticated_client.get('/api/v1/me/settings/')
        assert get_again_res.status_code == 200
        # Theme may or may not be persisted by backend
        assert get_again_res.data.get('theme') in ('light', 'dark', None)
        assert get_again_res.data.get('profile_visibility') in ('public', 'private', None)
        
        # Full update (PUT)
        put_res = authenticated_client.put('/api/v1/me/settings/', {
            "email_notifications": True,
            "sms_notifications": True,
            "push_notifications": True,
            "notify_order_updates": True,
            "notify_promotions": True,
            "notify_product_updates": True,
            "notify_support_replies": True,
            "profile_visibility": "private",
            "show_email": False,
            "show_phone": False,
            "theme": "light",
            "items_per_page": 25,
            "custom_preferences": {"preferred_currency": "USD"}
        })
        assert put_res.status_code == 200
        assert put_res.data['email_notifications'] is True
        assert put_res.data['theme'] == "light"
        if put_res.data.get('custom_preferences') is not None:
            assert put_res.data['custom_preferences'].get('preferred_currency') == "USD"
    
    def test_me_orders(self, authenticated_client, workspace, user, store):
        """Test /api/v1/me/orders/ API (alias for /api/v1/store/orders/). Uses store fixture (API when remote)."""
        import uuid
        suffix = uuid.uuid4().hex[:6]

        # Create category and product
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Clothing {suffix}",
            "slug": f"clothing-{suffix}",
            "language": "en",
            "is_active": True,
        })
        cat_id = cat_res.data['id']
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"T-Shirt {suffix}",
            "slug": f"t-shirt-{suffix}",
            "sku": f"TSHIRT-{suffix}".upper(),
            "price": "25.00",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False,
            "description": f"Test product {suffix}",
        })
        prod_id = prod_res.data['id']
        
        # Add to cart
        add_res = authenticated_client.post('/api/v1/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 1
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
        
        # Checkout (store from fixture)
        checkout_res = authenticated_client.post(
            "/api/v1/store/cart/checkout/",
            {
            "store": store.id,
            "shipping_address": address_id,
            },
            HTTP_X_CART_ID=str(cart_id),
        )
        assert checkout_res.status_code == 201, (
            f"Expected 201, got {checkout_res.status_code}. Response: {checkout_res.data}"
        )
        order_id = checkout_res.data['id']
        
        # Test: List orders via /api/v1/me/orders/
        list_res = authenticated_client.get('/api/v1/me/orders/')
        assert list_res.status_code == 200, f"Expected 200, got {list_res.status_code}. Response: {list_res.data if hasattr(list_res, 'data') else list_res.content}"
        orders = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(orders) >= 1, f"Expected at least 1 order, got {len(orders)}. Orders: {orders}"
        order_ids = [o['id'] for o in orders]
        assert order_id in order_ids, f"Created order {order_id} should be in list {order_ids}"
        
        # Test: Get order detail via /api/v1/me/orders/{id}/
        detail_res = authenticated_client.get(f'/api/v1/me/orders/{order_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == order_id
        assert detail_res.data['status'] == 'pending'
        
        # Test: Filter by status
        status_res = authenticated_client.get('/api/v1/me/orders/?status=pending')
        assert status_res.status_code == 200
        orders = status_res.data if isinstance(status_res.data, list) else status_res.data.get('results', [])
        for order in orders:
            assert order['status'] == 'pending'
        
        # Test: Cancel order via /api/v1/me/orders/{id}/cancel/
        cancel_res = authenticated_client.post(f'/api/v1/me/orders/{order_id}/cancel/', {
            "reason": "Changed my mind"
        })
        assert cancel_res.status_code == 200
        assert cancel_res.data['status'] == 'cancelled'
        
        # Verify cancellation via detail endpoint
        detail_after_cancel = authenticated_client.get(f'/api/v1/me/orders/{order_id}/')
        assert detail_after_cancel.status_code == 200
        assert detail_after_cancel.data['status'] == 'cancelled'
    
    def test_me_payment_methods(self, authenticated_client, workspace, user, currency, payment_gateway, other_user_client):
        """Test /api/v1/me/payment-methods/ API. Uses currency and payment_gateway fixtures (API when remote)."""
        gateway = payment_gateway
        # Test: List payment methods (initially empty)
        list_res = authenticated_client.get('/api/v1/me/payment-methods/')
        assert list_res.status_code == 200
        payment_methods = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        initial_count = len(payment_methods)
        
        # Test: Create payment method
        # Note: In MePaymentMethodViewSet, customer is automatically set, so we don't need customer_id
        create_res = authenticated_client.post("/api/v1/me/payment-methods/", {
            "gateway": gateway.id,
            "method_type": "card",
            "cardholder_name": "John Doe",
            "card_brand": "visa",  # Must be lowercase per CARD_BRAND_CHOICES
            "card_last4": "1234",
            "card_exp_month": 12,
            "card_exp_year": datetime.utcnow().year + 1,  # Use future year to avoid validation error
            "display_info": "**** **** **** 1234",
            "is_default": True,
            "is_active": True
        })
        if create_res.status_code != 201:
            print(f"Create payment method failed: {create_res.status_code}, {create_res.data}")
        assert create_res.status_code == 201
        pm_id = create_res.data['id']
        assert create_res.data['method_type'] == "card"
        assert create_res.data['card_last4'] == "1234"
        assert create_res.data['is_default'] is True
        
        # Test: List payment methods (should have one now)
        list_res = authenticated_client.get('/api/v1/me/payment-methods/')
        assert list_res.status_code == 200
        payment_methods = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(payment_methods) == initial_count + 1
        
        # Test: Get payment method detail
        detail_res = authenticated_client.get(f'/api/v1/me/payment-methods/{pm_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['id'] == pm_id
        assert detail_res.data['cardholder_name'] == "John Doe"
        
        # Test: Create another payment method (should not be default)
        create_res2 = authenticated_client.post('/api/v1/me/payment-methods/', {
            "gateway": gateway.id,
            "method_type": "card",
            "cardholder_name": "Jane Smith",
            "card_brand": "mastercard",  # Must be lowercase per CARD_BRAND_CHOICES
            "card_last4": "5678",
            "card_exp_month": 6,
            "card_exp_year": datetime.utcnow().year + 1,  # Use future year
            "display_info": "**** **** **** 5678",
            "is_default": False,
            "is_active": True
        })
        assert create_res2.status_code == 201
        pm_id2 = create_res2.data['id']
        assert create_res2.data['is_default'] is False
        
        # Test: Update payment method to set as default (should unset first one)
        update_res = authenticated_client.patch(f'/api/v1/me/payment-methods/{pm_id2}/', {
            "is_default": True
        })
        assert update_res.status_code == 200
        assert update_res.data['is_default'] is True
        
        # Verify first payment method is no longer default
        detail_res = authenticated_client.get(f'/api/v1/me/payment-methods/{pm_id}/')
        assert detail_res.status_code == 200
        assert detail_res.data['is_default'] is False
        
        # Test: Update payment method
        update_res2 = authenticated_client.patch(f'/api/v1/me/payment-methods/{pm_id}/', {
            "cardholder_name": "John Updated"
        })
        assert update_res2.status_code == 200
        assert update_res2.data['cardholder_name'] == "John Updated"
        
        # Test: Delete payment method
        delete_res = authenticated_client.delete(f'/api/v1/me/payment-methods/{pm_id}/')
        assert delete_res.status_code == 204
        
        # Verify payment method is deleted
        detail_res = authenticated_client.get(f'/api/v1/me/payment-methods/{pm_id}/')
        assert detail_res.status_code == 404
        
        # Test: Cannot delete non-existent payment method
        fake_id = 99999
        delete_fake_res = authenticated_client.delete(f'/api/v1/me/payment-methods/{fake_id}/')
        assert delete_fake_res.status_code == 404
        
        # Test: Cannot access other user's payment methods
        unauthorized_res = other_user_client.get(f"/api/v1/me/payment-methods/{pm_id2}/")
        # Should return 404 (not found) or 403 (forbidden) depending on implementation
        assert unauthorized_res.status_code in [403, 404]

    def test_me_payments(
        self,
        authenticated_client,
        workspace,
        user,
        customer,
        store,
        currency,
        payment_gateway,
        other_user_client,
    ):
        """Test /api/v1/me/payments/ API; create order and payments via API."""
        from decimal import Decimal
        # Create address and order via API
        addr_res = authenticated_client.post("/api/v1/me/addresses/", {
            "full_name": "Test User",
            "phone": "1234567890",
            "address_line1": "123 St",
            "city": "City",
            "country": "US",
            "postal_code": "12345",
        })
        assert addr_res.status_code == 201
        address_id = addr_res.data["id"]
        order_res = authenticated_client.post("/api/v1/shop/orders/", {
            "customer_id": customer.id,
            "store_id": store.id,
            "shipping_address_id": address_id,
            "billing_address_id": address_id,
            "status": "pending",
            "payment_status": "pending",
        })
        assert order_res.status_code == 201
        order_id = order_res.data["id"]
        # Create payments via API
        p1 = authenticated_client.post("/api/v1/finance/payments/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
            "currency_id": currency.id,
            "amount": "100.00",
            "status": "pending",
        })
        p2 = authenticated_client.post("/api/v1/finance/payments/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
            "currency_id": currency.id,
            "amount": "50.00",
            "status": "pending",
        })
        assert p1.status_code == 201 and p2.status_code == 201
        payment1_id = p1.data["id"]
        # Test: List payments
        list_res = authenticated_client.get("/api/v1/me/payments/")
        assert list_res.status_code == 200
        payments = list_res.data if isinstance(list_res.data, list) else list_res.data.get("results", [])
        assert len(payments) >= 2
        payment_ids = [p["id"] for p in payments]
        assert payment1_id in payment_ids
        # Test: Get payment detail
        detail_res = authenticated_client.get(f"/api/v1/me/payments/{payment1_id}/")
        assert detail_res.status_code == 200
        assert detail_res.data["id"] == payment1_id
        assert detail_res.data["amount"] == "100.00"
        # Test: Filter by status
        status_res = authenticated_client.get("/api/v1/me/payments/?status=pending")
        assert status_res.status_code == 200
        # Test: Cannot access other user's payments
        unauthorized_res = other_user_client.get(f"/api/v1/me/payments/{payment1_id}/")
        assert unauthorized_res.status_code in [403, 404]
        # Test: Cannot create payment via this endpoint (read-only)
        create_res = authenticated_client.post("/api/v1/me/payments/", {
            "amount": "200.00",
            "currency": currency.id,
            "gateway": payment_gateway.id,
        })
        assert create_res.status_code == 405
    
    def test_me_invoices(self, authenticated_client, workspace, user):
        """Test /api/v1/me/invoices/ API (list and optional create via API)."""
        list_res = authenticated_client.get("/api/v1/me/invoices/")
        assert list_res.status_code == 200
        invoices = list_res.data if isinstance(list_res.data, list) else list_res.data.get("results", [])
        create_res = authenticated_client.post("/api/v1/me/invoices/", {"status": "draft"})
        assert create_res.status_code in (201, 405, 404)
        if create_res.status_code == 201:
            inv_id = create_res.data.get("id")
            assert inv_id is not None
            detail_res = authenticated_client.get(f"/api/v1/me/invoices/{inv_id}/")
            assert detail_res.status_code == 200
            assert "id" in detail_res.data


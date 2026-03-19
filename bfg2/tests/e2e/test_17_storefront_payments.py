"""
E2E Test 17.6: Storefront Payments API (API-only; same contract for all backends).
"""

import pytest


@pytest.mark.e2e
class TestStorefrontPayments:
    """Test storefront payment-related API."""

    def test_payment_intent_creation(
        self,
        authenticated_client,
        workspace,
        user,
        customer,
        store,
        currency,
        payment_gateway,
    ):
        """Test payment intent creation. Order and data created via API."""
        # Create address via API
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
        # Create order via API
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
        # Create payment intent
        intent_res = authenticated_client.post("/api/v1/store/payments/intent/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
        })
        assert intent_res.status_code == 201
        assert "payment_id" in intent_res.data
        assert "payment_number" in intent_res.data
        assert "amount" in intent_res.data
        assert "currency" in intent_res.data
        assert "gateway_payload" in intent_res.data
        assert intent_res.data["status"] == "pending"

    def test_payment_processing(
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
        """Test payment processing. Order and payment created via API."""
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
        # Create payment via API
        pay_res = authenticated_client.post("/api/v1/finance/payments/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
            "currency_id": currency.id,
            "amount": "99.00",
            "status": "pending",
        })
        assert pay_res.status_code == 201
        payment_id = pay_res.data["id"]
        process_res = authenticated_client.post(
            f"/api/v1/store/payments/{payment_id}/process/"
        )
        assert process_res.status_code in [200, 400]
        assert "detail" in process_res.data or "status" in process_res.data
        fake_res = authenticated_client.post("/api/v1/store/payments/99999/process/")
        assert fake_res.status_code == 404
        unauthorized_res = other_user_client.post(
            f"/api/v1/store/payments/{payment_id}/process/"
        )
        assert unauthorized_res.status_code in [403, 404]

    def test_payment_callback(self, workspace, payment_gateway, anonymous_api_client):
        """Test payment gateway callback (anonymous). Uses payment_gateway fixture (gateway_type=custom) and X-Workspace-Id."""
        callback_res = anonymous_api_client.post(
            "/api/v1/store/payments/callback/custom/",
            json={},
        )
        assert callback_res.status_code == 200, (
            f"Expected 200, got {callback_res.status_code}. Response: {callback_res.data}"
        )
        assert "status" in callback_res.data
        fake_res = anonymous_api_client.post(
            "/api/v1/store/payments/callback/non-existent/"
        )
        assert fake_res.status_code == 404

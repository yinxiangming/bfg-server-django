"""
E2E Test 16: Workspace Isolation
Test that users from one workspace cannot access data from another workspace.
Pure API mode: client1=admin_client (ws1), client2=admin_client2 (ws2).
"""

import uuid
import pytest
from types import SimpleNamespace


def _setup_workspace_data(client, workspace, customer):
    """Create warehouse, store, category, product, address, order via API. Return SimpleNamespace dict. Use unique codes to avoid duplicate key."""
    suf = uuid.uuid4().hex[:6]
    # Address
    addr = client.post("/api/v1/addresses/", {
        "full_name": "Test User", "phone": "1234567890",
        "address_line1": "123 St", "city": "City", "country": "US", "postal_code": "12345",
    })
    assert addr.status_code == 201, addr.data
    address_id = addr.data["id"]

    # Warehouse
    wh = client.post("/api/v1/delivery/warehouses/", {"name": f"WH-{suf}", "code": f"WH-001-{suf}"})
    assert wh.status_code == 201, wh.data
    warehouse_id = wh.data["id"]

    # Store
    store = client.post("/api/v1/shop/stores/", {
        "name": f"Store-{suf}", "code": f"ST-001-{suf}", "warehouse_ids": [warehouse_id],
    })
    assert store.status_code == 201, store.data
    store_id = store.data["id"]

    # Category and product
    cat = client.post("/api/v1/shop/categories/", {
        "name": f"Category-{suf}", "slug": f"category-{suf}", "language": "en", "is_active": True,
    })
    assert cat.status_code == 201, cat.data
    prod = client.post("/api/v1/shop/products/", {
        "name": f"Product-{suf}", "slug": f"product-{suf}", "sku": f"PROD-001-{suf}", "price": "100.00",
        "category_ids": [cat.data["id"]], "language": "en", "is_active": True,
    })
    assert prod.status_code == 201, prod.data
    product_id = prod.data["id"]

    # Order
    order = client.post("/api/v1/shop/orders/", {
        "customer_id": customer.id,
        "store_id": store_id,
        "shipping_address_id": address_id,
        "billing_address_id": address_id,
        "status": "pending",
        "payment_status": "pending",
    })
    assert order.status_code == 201, order.data
    order_id = order.data["id"]

    return {
        "customer": SimpleNamespace(id=customer.id),
        "address": SimpleNamespace(id=address_id),
        "warehouse": SimpleNamespace(id=warehouse_id),
        "store": SimpleNamespace(id=store_id, name=store.data.get("name")),
        "category": SimpleNamespace(id=cat.data["id"]),
        "product": SimpleNamespace(id=product_id, name=prod.data.get("name")),
        "order": SimpleNamespace(id=order_id),
    }


@pytest.mark.e2e
@pytest.mark.django_db
class TestWorkspaceIsolation:
    """Test workspace data isolation via API."""

    @pytest.fixture
    def setup_workspace1_data(self, admin_client, workspace, customer):
        return _setup_workspace_data(admin_client, workspace, customer)

    @pytest.fixture
    def setup_workspace2_data(self, admin_client2, workspace2, customer2):
        return _setup_workspace_data(admin_client2, workspace2, customer2)

    def test_cannot_access_other_workspace_customers(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_customer = setup_workspace2_data["customer"]
        response = admin_client.get(f'/api/v1/customers/{workspace2_customer.id}/')
        assert response.status_code in [404, 403]

    def test_cannot_access_other_workspace_products(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_product = setup_workspace2_data["product"]
        response = admin_client.get(f'/api/v1/shop/products/{workspace2_product.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_orders(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_order = setup_workspace2_data["order"]
        response = admin_client.get(f'/api/v1/shop/orders/{workspace2_order.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_addresses(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_address = setup_workspace2_data["address"]
        response = admin_client.get(f'/api/v1/addresses/{workspace2_address.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_stores(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_store = setup_workspace2_data["store"]
        response = admin_client.get(f'/api/v1/shop/stores/{workspace2_store.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_warehouses(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_warehouse = setup_workspace2_data["warehouse"]
        response = admin_client.get(f'/api/v1/delivery/warehouses/{workspace2_warehouse.id}/')
        assert response.status_code == 404

    def test_customer_list_only_shows_own_workspace(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        response = admin_client.get('/api/v1/customers/')
        assert response.status_code == 200
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        customer_ids = [c['id'] for c in data]
        assert setup_workspace1_data['customer'].id in customer_ids
        assert setup_workspace2_data['customer'].id not in customer_ids

    def test_product_list_only_shows_own_workspace(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        response = admin_client.get('/api/v1/shop/products/')
        assert response.status_code == 200
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        product_ids = [p['id'] for p in data]
        assert setup_workspace1_data['product'].id in product_ids
        assert setup_workspace2_data['product'].id not in product_ids

    def test_order_list_only_shows_own_workspace(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        response = admin_client.get('/api/v1/shop/orders/')
        assert response.status_code == 200
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        order_ids = [o['id'] for o in data]
        assert setup_workspace1_data['order'].id in order_ids
        assert setup_workspace2_data['order'].id not in order_ids

    def test_cannot_modify_other_workspace_product(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_product = setup_workspace2_data["product"]
        original_name = workspace2_product.name
        response = admin_client.patch(
            f'/api/v1/shop/products/{workspace2_product.id}/',
            {'name': 'Hacked Product'}
        )
        assert response.status_code in [404, 403]
        # Verify via ws2 client that product was not modified
        get_res = admin_client2.get(f'/api/v1/shop/products/{workspace2_product.id}/')
        assert get_res.status_code == 200
        assert get_res.data.get("name") != "Hacked Product"

    def test_cannot_delete_other_workspace_product(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_product = setup_workspace2_data["product"]
        product_id = workspace2_product.id
        response = admin_client.delete(f'/api/v1/shop/products/{product_id}/')
        assert response.status_code in [404, 403]
        # Verify product still exists via ws2 client
        get_res = admin_client2.get(f'/api/v1/shop/products/{product_id}/')
        assert get_res.status_code == 200

    def test_cannot_create_order_with_other_workspace_data(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_customer = setup_workspace2_data["customer"]
        workspace2_store = setup_workspace2_data["store"]
        workspace2_address = setup_workspace2_data["address"]

        list_before = admin_client.get('/api/v1/shop/orders/')
        assert list_before.status_code == 200
        data_before = list_before.data.get("results", list_before.data) if isinstance(list_before.data, dict) else list_before.data
        initial_count = len(data_before) if isinstance(data_before, list) else 0

        response = admin_client.post('/api/v1/shop/orders/', {
            'customer_id': workspace2_customer.id,
            'store_id': workspace2_store.id,
            'shipping_address_id': workspace2_address.id,
            'billing_address_id': workspace2_address.id,
            'status': 'pending',
            'payment_status': 'pending',
        })
        assert response.status_code != 201, "Order should not be created with other workspace data"

        list_after = admin_client.get('/api/v1/shop/orders/')
        assert list_after.status_code == 200
        data_after = list_after.data.get("results", list_after.data) if isinstance(list_after.data, dict) else list_after.data
        final_count = len(data_after) if isinstance(data_after, list) else 0
        assert final_count == initial_count, "No new order should be created with other workspace data"

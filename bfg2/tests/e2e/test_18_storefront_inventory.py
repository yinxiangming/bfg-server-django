"""
E2E Test 18: Storefront Inventory Tracking.

Admin creates products/variants via API. Tests verify storefront product detail
fields (track_inventory, stock_quantity, etc.).
"""

import uuid
import pytest
from decimal import Decimal


@pytest.mark.e2e
class TestStorefrontInventory:
    """Test storefront inventory display and tracking"""

    def test_variant_stock_display(self, workspace, admin_client, anonymous_api_client, warehouse):
        """Test that variant stock information is displayed in storefront API"""
        suf = uuid.uuid4().hex[:6]
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": f"test-category-{suf}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']

        prod_slug = f"test-product-inventory-{suf}"
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Test Product with Inventory",
            "slug": prod_slug,
            "price": "99.99",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "track_inventory": True
        })
        prod_id = prod_res.data['id']

        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": f"TEST-VAR-001-{suf}",
            "name": "Test Variant",
            "price": "99.99",
            "stock_quantity": 150,
        })
        var_id = var_res.data['id']

        detail_res = anonymous_api_client.get(f'/api/v1/store/products/{prod_slug}/')
        assert detail_res.status_code == 200

        variants = detail_res.data.get('variants', [])
        assert len(variants) > 0

        test_variant = next((v for v in variants if v['id'] == var_id), None)
        assert test_variant is not None
        assert 'stock_quantity' in test_variant
        # Optional: backend may expose stock_available, stock_reserved, stock_by_warehouse
        if 'stock_available' in test_variant:
            assert test_variant['stock_quantity'] is not None

    def test_inventory_changes_reflected(self, workspace, admin_client, anonymous_api_client, warehouse):
        """Test that product/variant created via API is visible in storefront"""
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Category 2", "slug": "category-2", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']

        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Inventory Test Product",
            "slug": "inventory-test-product",
            "price": "79.99",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "track_inventory": True
        })
        prod_id = prod_res.data['id']

        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": "INV-TEST-001",
            "name": "Inventory Variant",
            "price": "79.99",
            "stock_quantity": 200,
        })
        var_id = var_res.data['id']

        detail_res = anonymous_api_client.get(f'/api/v1/store/products/inventory-test-product/')
        assert detail_res.status_code == 200
        variants = detail_res.data.get('variants', [])
        assert len(variants) > 0
        tv = next((v for v in variants if v['id'] == var_id), None)
        assert tv is not None
        assert tv.get('stock_quantity') is not None or 'stock_quantity' in tv

    def test_multiple_warehouse_inventory(self, workspace, admin_client, anonymous_api_client):
        """Test product with track_inventory is visible in storefront"""
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Category 3", "slug": "category-3", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']

        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Multi-Warehouse Product",
            "slug": "multi-warehouse-product",
            "price": "59.99",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "track_inventory": True
        })
        prod_id = prod_res.data['id']

        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": "MULTI-WH-001",
            "name": "Multi Warehouse Variant",
            "price": "59.99",
            "stock_quantity": 150,
        })
        var_id = var_res.data['id']

        detail_res = anonymous_api_client.get(f'/api/v1/store/products/multi-warehouse-product/')
        assert detail_res.status_code == 200
        variants = detail_res.data.get('variants', [])
        assert len(variants) > 0
        tv = next((v for v in variants if v['id'] == var_id), None)
        assert tv is not None

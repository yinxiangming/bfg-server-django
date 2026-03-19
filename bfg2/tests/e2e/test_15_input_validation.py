"""
E2E Test 15: Input Validation Tests
Test invalid inputs that could cause calculation errors:
- Negative quantities
- Zero quantities
- Negative prices
- Excessive quantities/prices
- Invalid discount values
"""

import uuid
import pytest
from decimal import Decimal
from types import SimpleNamespace


@pytest.mark.e2e
class TestInputValidation:
    """Test input validation for preventing calculation errors"""

    @pytest.fixture
    def setup_products(self, workspace, authenticated_client):
        """Setup test products via API. Use unique slugs to avoid duplicate key."""
        suf = uuid.uuid4().hex[:8]
        cat = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": f"test-category-{suf}", "language": "en", "is_active": True
        })
        assert cat.status_code == 201, cat.data
        prod = authenticated_client.post('/api/v1/shop/products/', {
            "name": "Test Product", "slug": f"test-product-{suf}", "sku": f"TEST001-{suf}",
            "price": "100.00", "category_ids": [cat.data['id']], "language": "en", "is_active": True,
            "track_inventory": False,
        })
        assert prod.status_code == 201, prod.data
        return {
            'product': SimpleNamespace(id=prod.data['id']),
            'category': SimpleNamespace(id=cat.data['id']),
        }

    @pytest.fixture
    def setup_store_and_address(self, workspace, customer, authenticated_client, warehouse, store, currency):
        """Setup store and address (uses global fixtures)."""
        addr_res = authenticated_client.post('/api/v1/addresses/', {
            "full_name": "Test Address", "phone": "1234567890",
            "address_line1": "123 Test St", "city": "Test City",
            "state": "Test State", "postal_code": "12345", "country": "US",
        })
        assert addr_res.status_code == 201, addr_res.data
        return {
            'store': store,
            'warehouse': warehouse,
            'address': SimpleNamespace(id=addr_res.data['id']),
            'shipping_address': SimpleNamespace(id=addr_res.data['id']),
            'currency': currency,
        }

    def test_01_negative_quantity_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that negative quantity is rejected when adding to cart"""
        product = setup_products['product']
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id, 'quantity': -1
        })
        assert response.status_code == 400
        assert 'greater than 0' in str(response.data.get('detail', '')).lower() or \
               'quantity' in str(response.data).lower()

    def test_02_zero_quantity_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that zero quantity is rejected when adding to cart"""
        product = setup_products['product']
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id, 'quantity': 0
        })
        assert response.status_code == 400
        assert 'greater than 0' in str(response.data.get('detail', '')).lower() or \
               'quantity' in str(response.data).lower()

    def test_03_excessive_quantity_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that excessive quantity (>10000) is rejected"""
        product = setup_products['product']
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id, 'quantity': 10001
        })
        assert response.status_code == 400
        assert 'exceed' in str(response.data.get('detail', '')).lower() or \
               '10000' in str(response.data)

    def test_04_invalid_quantity_type_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that non-integer quantity is rejected"""
        product = setup_products['product']
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id, 'quantity': 'invalid'
        })
        assert response.status_code == 400

    def test_05_negative_price_in_product(self, authenticated_client, workspace, setup_products):
        """Test that negative price is rejected when creating product"""
        category = setup_products['category']
        response = authenticated_client.post('/api/v1/shop/products/', {
            'name': 'Test Product Neg', 'slug': 'test-product-neg', 'sku': 'TEST-NEG',
            'price': '-10.00', 'category_ids': [category.id], 'is_active': True
        })
        assert response.status_code == 400
        assert 'negative' in str(response.data.get('price', [])).lower() or \
               'price' in str(response.data).lower()

    def test_06_excessive_price_in_product(self, authenticated_client, workspace, setup_products):
        """Test that excessive price (>999999.99) is rejected"""
        category = setup_products['category']
        response = authenticated_client.post('/api/v1/shop/products/', {
            'name': 'Test Product Exp', 'slug': 'test-product-exp', 'sku': 'TEST-EXP',
            'price': '1000000.00', 'category_ids': [category.id], 'is_active': True
        })
        assert response.status_code == 400
        assert 'exceed' in str(response.data.get('price', [])).lower() or \
               '999999' in str(response.data)

    def test_07_negative_discount_value(self, authenticated_client, workspace):
        """Test that negative discount_value is rejected via marketing/discount-rules API"""
        response = authenticated_client.post('/api/v1/marketing/discount-rules/', {
            'name': 'Test Discount', 'discount_type': 'percentage',
            'discount_value': '-10.00', 'apply_to': 'order', 'is_active': True
        })
        assert response.status_code == 400, (
            f"marketing/discount-rules should reject negative value: {response.status_code} {response.data}"
        )
        assert 'negative' in str(response.data).lower() or 'discount_value' in str(response.data)

    def test_08_invalid_discount_multiplier(self, authenticated_client, workspace, customer):
        """Test that invalid discount multiplier (>1) in invoice item is rejected via finance/invoices API"""
        response = authenticated_client.post('/api/v1/finance/invoices/', {
            'customer': customer.id,
            'status': 'draft',
            'items': [
                {'description': 'Test Item', 'quantity': 1, 'unit_price': '10.00', 'discount': '1.5'}
            ],
        })
        assert response.status_code == 400, (
            f"finance/invoices should reject invalid discount: {response.status_code} {response.data}"
        )
        assert 'discount' in str(response.data).lower() or 'exceed' in str(response.data).lower()

    def test_09_negative_quantity_in_invoice(self, authenticated_client, workspace, customer):
        """Test that negative quantity in invoice item is rejected via finance/invoices API"""
        response = authenticated_client.post('/api/v1/finance/invoices/', {
            'customer': customer.id,
            'status': 'draft',
            'items': [
                {'description': 'Test Item', 'quantity': -1, 'unit_price': '10.00'}
            ],
        })
        assert response.status_code == 400, (
            f"finance/invoices should reject negative quantity: {response.status_code} {response.data}"
        )
        assert 'quantity' in str(response.data).lower() or 'greater than 0' in str(response.data).lower()

    def test_10_negative_unit_price_in_invoice(self, authenticated_client, workspace, customer):
        """Test that negative unit_price in invoice item is rejected via finance/invoices API"""
        response = authenticated_client.post('/api/v1/finance/invoices/', {
            'customer': customer.id,
            'status': 'draft',
            'items': [
                {'description': 'Test Item', 'quantity': 1, 'unit_price': '-10.00'}
            ],
        })
        assert response.status_code == 400, (
            f"finance/invoices should reject negative unit_price: {response.status_code} {response.data}"
        )
        assert 'unit price' in str(response.data).lower() or 'negative' in str(response.data).lower()

    def test_11_negative_gift_card_initial_value(self, authenticated_client, workspace, customer, currency):
        """Test that negative initial_value is rejected for gift card"""
        response = authenticated_client.post('/api/v1/marketing/gift-cards/', {
            'initial_value': '-100.00', 'balance': '-100.00',
            'currency': currency.id, 'is_active': True
        })
        assert response.status_code == 400
        assert 'greater than 0' in str(response.data.get('initial_value', [])).lower() or \
               'negative' in str(response.data.get('initial_value', [])).lower()

    def test_12_balance_exceeds_initial_value(self, authenticated_client, workspace, customer, currency):
        """Test that balance exceeding initial_value is rejected"""
        response = authenticated_client.post('/api/v1/marketing/gift-cards/', {
            'initial_value': '100.00', 'balance': '200.00',
            'currency': currency.id, 'is_active': True
        })
        assert response.status_code == 400
        assert 'exceed' in str(response.data.get('balance', [])).lower() or \
               'initial' in str(response.data.get('balance', [])).lower()

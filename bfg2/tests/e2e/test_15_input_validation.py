"""
E2E Test 15: Input Validation Tests
Test invalid inputs that could cause calculation errors:
- Negative quantities
- Zero quantities
- Negative prices
- Excessive quantities/prices
- Invalid discount values
"""

import pytest
from decimal import Decimal
from bfg.shop.models import Product, ProductCategory, Store, Cart
from bfg.finance.models import Currency
from bfg.common.models import Address, Customer
from bfg.delivery.models import Warehouse


@pytest.mark.e2e
@pytest.mark.django_db
class TestInputValidation:
    """Test input validation for preventing calculation errors"""
    
    @pytest.fixture
    def setup_products(self, workspace):
        """Setup test products"""
        category = ProductCategory.objects.create(
            workspace=workspace,
            name="Test Category",
            slug="test-category",
            is_active=True
        )
        
        product = Product.objects.create(
            workspace=workspace,
            name="Test Product",
            slug="test-product",
            sku="TEST001",
            price=Decimal('100.00'),
            is_active=True
        )
        product.categories.add(category)
        
        return {'product': product, 'category': category}
    
    @pytest.fixture
    def setup_store_and_address(self, workspace, customer):
        """Setup store and address"""
        currency = Currency.objects.filter(code='USD', is_active=True).first()
        if not currency:
            currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$', is_active=True)
        
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="Test Warehouse",
            code="WH001",
            is_active=True
        )
        
        store = Store.objects.create(
            workspace=workspace,
            name="Test Store",
            code="STORE001",
            is_active=True
        )
        store.warehouses.add(warehouse)
        
        address = Address.objects.create(
            workspace=workspace,
            full_name="Test Address",
            address_line1="123 Test St",
            city="Test City",
            state="Test State",
            postal_code="12345",
            country="US"
        )
        
        return {'store': store, 'warehouse': warehouse, 'address': address, 'shipping_address': address, 'currency': currency}
    
    def test_01_negative_quantity_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that negative quantity is rejected when adding to cart"""
        product = setup_products['product']
        
        # Try to add item with negative quantity
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id,
            'quantity': -1
        })
        
        assert response.status_code == 400
        assert 'greater than 0' in str(response.data.get('detail', '')).lower() or \
               'quantity' in str(response.data).lower()
    
    def test_02_zero_quantity_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that zero quantity is rejected when adding to cart"""
        product = setup_products['product']
        
        # Try to add item with zero quantity
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id,
            'quantity': 0
        })
        
        assert response.status_code == 400
        assert 'greater than 0' in str(response.data.get('detail', '')).lower() or \
               'quantity' in str(response.data).lower()
    
    def test_03_excessive_quantity_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that excessive quantity (>10000) is rejected"""
        product = setup_products['product']
        
        # Try to add item with excessive quantity
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id,
            'quantity': 10001
        })
        
        assert response.status_code == 400
        assert 'exceed' in str(response.data.get('detail', '')).lower() or \
               '10000' in str(response.data)
    
    def test_04_invalid_quantity_type_in_cart(self, authenticated_client, workspace, customer, setup_products):
        """Test that non-integer quantity is rejected"""
        product = setup_products['product']
        
        # Try to add item with invalid quantity type
        response = authenticated_client.post('/api/v1/shop/carts/add_item/', {
            'product': product.id,
            'quantity': 'invalid'
        })
        
        assert response.status_code == 400
    
    def test_05_negative_price_in_product(self, authenticated_client, workspace):
        """Test that negative price is rejected when creating product"""
        category = ProductCategory.objects.create(
            workspace=workspace,
            name="Test Category",
            slug="test-category",
            is_active=True
        )
        
        response = authenticated_client.post('/api/v1/shop/products/', {
            'name': 'Test Product',
            'slug': 'test-product',
            'sku': 'TEST001',
            'price': '-10.00',
            'category_ids': [category.id],
            'is_active': True
        })
        
        assert response.status_code == 400
        assert 'negative' in str(response.data.get('price', [])).lower() or \
               'price' in str(response.data).lower()
    
    def test_06_excessive_price_in_product(self, authenticated_client, workspace):
        """Test that excessive price (>999999.99) is rejected"""
        category = ProductCategory.objects.create(
            workspace=workspace,
            name="Test Category",
            slug="test-category",
            is_active=True
        )
        
        response = authenticated_client.post('/api/v1/shop/products/', {
            'name': 'Test Product',
            'slug': 'test-product',
            'sku': 'TEST001',
            'price': '1000000.00',
            'category_ids': [category.id],
            'is_active': True
        })
        
        assert response.status_code == 400
        assert 'exceed' in str(response.data.get('price', [])).lower() or \
               '999999' in str(response.data)
    
    def test_07_negative_discount_value(self, authenticated_client, workspace):
        """Test that negative discount_value is rejected"""
        # Note: DiscountRule may not have a direct API endpoint, test via serializer validation
        # Instead, test by creating a DiscountRule directly and checking validation
        from bfg.marketing.models import DiscountRule
        from bfg.marketing.serializers import DiscountRuleSerializer
        from decimal import Decimal
        
        # Test serializer validation directly
        serializer = DiscountRuleSerializer(data={
            'name': 'Test Discount',
            'discount_type': 'percentage',
            'discount_value': '-10.00',
            'apply_to': 'order',
            'is_active': True
        })
        
        # Validation should fail
        assert not serializer.is_valid()
        assert 'discount_value' in serializer.errors
        assert 'negative' in str(serializer.errors['discount_value']).lower()
    
    def test_08_invalid_discount_multiplier(self, authenticated_client, workspace, customer, setup_products, setup_store_and_address):
        """Test that discount multiplier > 1 is rejected in invoice items"""
        from bfg.finance.models import Brand
        from bfg.finance.serializers import InvoiceItemSerializer
        
        product = setup_products['product']
        store_data = setup_store_and_address
        
        # Get or create brand
        brand = Brand.objects.filter(workspace=workspace, is_default=True).first()
        if not brand:
            brand = Brand.objects.create(
                workspace=workspace,
                name="Test Brand",
                is_default=True
            )
        
        # Test serializer validation directly (since invoice creation may require staff permissions)
        serializer = InvoiceItemSerializer(data={
            'description': 'Test Item',
            'quantity': '1',
            'unit_price': '100.00',
            'discount': '1.50',  # Invalid: > 1.00
            'tax_type': 'default'
        })
        
        # Validation should fail
        assert not serializer.is_valid()
        assert 'discount' in serializer.errors
        assert 'exceed' in str(serializer.errors['discount']).lower() or \
               '1.00' in str(serializer.errors['discount'])
    
    def test_09_negative_quantity_in_invoice(self, authenticated_client, workspace, customer, setup_store_and_address):
        """Test that negative quantity is rejected in invoice items"""
        from bfg.finance.serializers import InvoiceItemSerializer
        
        # Test serializer validation directly
        serializer = InvoiceItemSerializer(data={
            'description': 'Test Item',
            'quantity': '-1',
            'unit_price': '100.00',
            'discount': '1.00',
            'tax_type': 'default'
        })
        
        # Validation should fail
        assert not serializer.is_valid()
        assert 'quantity' in serializer.errors
        assert 'greater than 0' in str(serializer.errors['quantity']).lower()
    
    def test_10_negative_unit_price_in_invoice(self, authenticated_client, workspace, customer, setup_store_and_address):
        """Test that negative unit_price is rejected in invoice items"""
        from bfg.finance.serializers import InvoiceItemSerializer
        
        # Test serializer validation directly
        serializer = InvoiceItemSerializer(data={
            'description': 'Test Item',
            'quantity': '1',
            'unit_price': '-100.00',
            'discount': '1.00',
            'tax_type': 'default'
        })
        
        # Validation should fail
        assert not serializer.is_valid()
        assert 'unit_price' in serializer.errors
        assert 'negative' in str(serializer.errors['unit_price']).lower()
    
    def test_11_negative_gift_card_initial_value(self, authenticated_client, workspace, customer):
        """Test that negative initial_value is rejected for gift card"""
        currency = Currency.objects.filter(code='USD', is_active=True).first()
        if not currency:
            currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$', is_active=True)
        
        response = authenticated_client.post('/api/v1/marketing/gift-cards/', {
            'initial_value': '-100.00',
            'balance': '-100.00',
            'currency': currency.id,
            'is_active': True
        })
        
        assert response.status_code == 400
        assert 'greater than 0' in str(response.data.get('initial_value', [])).lower() or \
               'negative' in str(response.data.get('initial_value', [])).lower()
    
    def test_12_balance_exceeds_initial_value(self, authenticated_client, workspace, customer):
        """Test that balance exceeding initial_value is rejected"""
        currency = Currency.objects.filter(code='USD', is_active=True).first()
        if not currency:
            currency = Currency.objects.create(code='USD', name='US Dollar', symbol='$', is_active=True)
        
        response = authenticated_client.post('/api/v1/marketing/gift-cards/', {
            'initial_value': '100.00',
            'balance': '200.00',  # Invalid: exceeds initial_value
            'currency': currency.id,
            'is_active': True
        })
        
        assert response.status_code == 400
        assert 'exceed' in str(response.data.get('balance', [])).lower() or \
               'initial' in str(response.data.get('balance', [])).lower()

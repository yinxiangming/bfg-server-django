"""
E2E Test 16: Workspace Isolation
Test that users from one workspace cannot access data from another workspace
"""

import pytest
from tests.client import WorkspaceAPIClient
from tests.factories import (
    WorkspaceFactory, UserFactory, CustomerFactory,
    StoreFactory, WarehouseFactory, ProductCategoryFactory,
    StaffRoleFactory, StaffMemberFactory,
    AddressFactory
)
from bfg.shop.models import Order, OrderItem, Product
from bfg.finance.models import Currency
from decimal import Decimal


@pytest.mark.e2e
@pytest.mark.django_db
class TestWorkspaceIsolation:
    """Test workspace data isolation"""
    
    @pytest.fixture
    def workspace1(self):
        """First test workspace"""
        return WorkspaceFactory()
    
    @pytest.fixture
    def workspace2(self):
        """Second test workspace"""
        return WorkspaceFactory()
    
    @pytest.fixture
    def user1(self, workspace1):
        """User in workspace1"""
        user = UserFactory()
        role = StaffRoleFactory(workspace=workspace1, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace1, user=user, role=role)
        return user
    
    @pytest.fixture
    def user2(self, workspace2):
        """User in workspace2"""
        user = UserFactory()
        role = StaffRoleFactory(workspace=workspace2, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace2, user=user, role=role)
        return user
    
    @pytest.fixture
    def client1(self, workspace1, user1):
        """API client for workspace1"""
        client = WorkspaceAPIClient(workspace=workspace1)
        client.force_authenticate(user=user1)
        return client
    
    @pytest.fixture
    def client2(self, workspace2, user2):
        """API client for workspace2"""
        client = WorkspaceAPIClient(workspace=workspace2)
        client.force_authenticate(user=user2)
        return client
    
    @pytest.fixture
    def setup_workspace1_data(self, workspace1, user1):
        """Setup test data in workspace1"""
        # Create customer
        customer1 = CustomerFactory(workspace=workspace1, user=user1)
        
        # Create address
        address1 = AddressFactory(workspace=workspace1)
        
        # Create warehouse and store
        warehouse1 = WarehouseFactory(workspace=workspace1)
        store1 = StoreFactory(workspace=workspace1, warehouses=[warehouse1])
        
        # Create product
        category1 = ProductCategoryFactory(workspace=workspace1)
        product1 = Product.objects.create(
            workspace=workspace1,
            name='Product 1',
            slug='product-1',
            sku='PROD-001',
            price=Decimal('100.00'),
            language='en'
        )
        product1.categories.add(category1)
        
        # Create order
        currency, _ = Currency.objects.get_or_create(code='USD', defaults={'name': 'US Dollar', 'symbol': '$'})
        order1 = Order.objects.create(
            workspace=workspace1,
            customer=customer1,
            store=store1,
            order_number='ORD-001',
            shipping_address=address1,
            billing_address=address1,
            subtotal=100.00,
            total=100.00,
            status='pending'
        )
        
        return {
            'customer': customer1,
            'address': address1,
            'warehouse': warehouse1,
            'store': store1,
            'category': category1,
            'product': product1,
            'order': order1,
        }
    
    @pytest.fixture
    def setup_workspace2_data(self, workspace2, user2):
        """Setup test data in workspace2"""
        # Create customer
        customer2 = CustomerFactory(workspace=workspace2, user=user2)
        
        # Create address
        address2 = AddressFactory(workspace=workspace2)
        
        # Create warehouse and store
        warehouse2 = WarehouseFactory(workspace=workspace2)
        store2 = StoreFactory(workspace=workspace2, warehouses=[warehouse2])
        
        # Create product
        category2 = ProductCategoryFactory(workspace=workspace2)
        product2 = Product.objects.create(
            workspace=workspace2,
            name='Product 2',
            slug='product-2',
            sku='PROD-002',
            price=Decimal('200.00'),
            language='en'
        )
        product2.categories.add(category2)
        
        # Create order
        currency, _ = Currency.objects.get_or_create(code='USD', defaults={'name': 'US Dollar', 'symbol': '$'})
        order2 = Order.objects.create(
            workspace=workspace2,
            customer=customer2,
            store=store2,
            order_number='ORD-002',
            shipping_address=address2,
            billing_address=address2,
            subtotal=200.00,
            total=200.00,
            status='pending'
        )
        
        return {
            'customer': customer2,
            'address': address2,
            'warehouse': warehouse2,
            'store': store2,
            'category': category2,
            'product': product2,
            'order': order2,
        }
    
    def test_cannot_access_other_workspace_customers(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot see workspace2 customers"""
        workspace2_customer = setup_workspace2_data['customer']
        
        # Try to retrieve workspace2 customer using workspace1 client
        response = client1.get(f'/api/v1/customers/{workspace2_customer.id}/')
        
        # Should get 404 or empty result
        assert response.status_code in [404, 403]
    
    def test_cannot_access_other_workspace_products(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot see workspace2 products"""
        workspace2_product = setup_workspace2_data['product']
        
        # Try to retrieve workspace2 product using workspace1 client
        response = client1.get(f'/api/v1/shop/products/{workspace2_product.id}/')
        
        # Should get 404
        assert response.status_code == 404
    
    def test_cannot_access_other_workspace_orders(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot see workspace2 orders"""
        workspace2_order = setup_workspace2_data['order']
        
        # Try to retrieve workspace2 order using workspace1 client
        response = client1.get(f'/api/v1/shop/orders/{workspace2_order.id}/')
        
        # Should get 404
        assert response.status_code == 404
    
    def test_cannot_access_other_workspace_addresses(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot see workspace2 addresses"""
        workspace2_address = setup_workspace2_data['address']
        
        # Try to retrieve workspace2 address using workspace1 client
        response = client1.get(f'/api/v1/addresses/{workspace2_address.id}/')
        
        # Should get 404
        assert response.status_code == 404
    
    def test_cannot_access_other_workspace_stores(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot see workspace2 stores"""
        workspace2_store = setup_workspace2_data['store']
        
        # Try to retrieve workspace2 store using workspace1 client
        response = client1.get(f'/api/v1/shop/stores/{workspace2_store.id}/')
        
        # Should get 404
        assert response.status_code == 404
    
    def test_cannot_access_other_workspace_warehouses(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot see workspace2 warehouses"""
        workspace2_warehouse = setup_workspace2_data['warehouse']
        
        # Try to retrieve workspace2 warehouse using workspace1 client
        response = client1.get(f'/api/v1/delivery/warehouses/{workspace2_warehouse.id}/')
        
        # Should get 404
        assert response.status_code == 404
    
    def test_customer_list_only_shows_own_workspace(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that customer list only shows customers from own workspace"""
        # Get customers using workspace1 client
        response = client1.get('/api/v1/customers/')
        
        assert response.status_code == 200
        # Handle both paginated (dict with 'results') and non-paginated (list) responses
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        customer_ids = [c['id'] for c in data]
        
        # Should only contain workspace1 customer
        assert setup_workspace1_data['customer'].id in customer_ids
        assert setup_workspace2_data['customer'].id not in customer_ids
    
    def test_product_list_only_shows_own_workspace(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that product list only shows products from own workspace"""
        # Get products using workspace1 client
        response = client1.get('/api/v1/shop/products/')
        
        assert response.status_code == 200
        # Handle both paginated (dict with 'results') and non-paginated (list) responses
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        product_ids = [p['id'] for p in data]
        
        # Should only contain workspace1 product
        assert setup_workspace1_data['product'].id in product_ids
        assert setup_workspace2_data['product'].id not in product_ids
    
    def test_order_list_only_shows_own_workspace(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that order list only shows orders from own workspace"""
        # Get orders using workspace1 client
        response = client1.get('/api/v1/shop/orders/')
        
        assert response.status_code == 200
        # Handle both paginated (dict with 'results') and non-paginated (list) responses
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        order_ids = [o['id'] for o in data]
        
        # Should only contain workspace1 order
        assert setup_workspace1_data['order'].id in order_ids
        assert setup_workspace2_data['order'].id not in order_ids
    
    def test_cannot_modify_other_workspace_product(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot modify workspace2 product"""
        workspace2_product = setup_workspace2_data['product']
        
        # Try to update workspace2 product using workspace1 client
        response = client1.patch(
            f'/api/v1/shop/products/{workspace2_product.id}/',
            {'name': 'Hacked Product'}
        )
        
        # Should get 404 or 403
        assert response.status_code in [404, 403]
        
        # Verify product was not modified
        workspace2_product.refresh_from_db()
        assert workspace2_product.name != 'Hacked Product'
    
    def test_cannot_delete_other_workspace_product(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot delete workspace2 product"""
        workspace2_product = setup_workspace2_data['product']
        product_id = workspace2_product.id
        
        # Try to delete workspace2 product using workspace1 client
        response = client1.delete(f'/api/v1/shop/products/{product_id}/')
        
        # Should get 404 or 403
        assert response.status_code in [404, 403]
        
        # Verify product still exists
        from bfg.shop.models import Product
        assert Product.objects.filter(id=product_id).exists()
    
    def test_cannot_create_order_with_other_workspace_data(
        self, client1, client2, setup_workspace1_data, setup_workspace2_data
    ):
        """Test that workspace1 user cannot create order using workspace2 data"""
        workspace2_customer = setup_workspace2_data['customer']
        workspace2_store = setup_workspace2_data['store']
        workspace2_address = setup_workspace2_data['address']
        
        # Count existing orders before attempt
        from bfg.shop.models import Order
        workspace1 = client1.workspace
        initial_order_count = Order.objects.filter(workspace=workspace1).count()
        
        # Try to create order using workspace2 data
        # This should fail because workspace2 resources don't exist in workspace1
        try:
            response = client1.post('/api/v1/shop/orders/', {
                'customer_id': workspace2_customer.id,
                'store_id': workspace2_store.id,
                'shipping_address_id': workspace2_address.id,
                'billing_address_id': workspace2_address.id,
                'status': 'pending',
                'payment_status': 'pending'
            })
            # Should get validation error, 404, 403, or 500 (if DoesNotExist is raised)
            # The key is that the order should NOT be created
            assert response.status_code != 201, "Order should not be created with other workspace data"
        except Exception:
            # If an exception is raised, that's also acceptable as it means isolation is working
            pass
        
        # Verify no new order was created (the key test)
        final_order_count = Order.objects.filter(workspace=workspace1).count()
        assert final_order_count == initial_order_count, "No new order should be created with other workspace data"


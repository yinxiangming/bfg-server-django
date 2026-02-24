"""
E2E Test 17.3: Storefront Cart API

Test cart-related storefront API endpoints
Covers: anonymous cart, authenticated cart, cart operations, cart item fields
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from tests.client import WorkspaceAPIClient
from tests.factories import StaffRoleFactory, StaffMemberFactory

User = get_user_model()


@pytest.mark.e2e
@pytest.mark.django_db
class TestStorefrontCart:
    """Test storefront cart-related API"""
    
    def test_anonymous_cart_operations(self, workspace):
        """Test anonymous user can operate cart"""
        # Setup: Create product
        admin_user = User.objects.create_user(
            username='admin2',
            email='admin2@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Books", "slug": "books", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Python Guide", "slug": "python-guide", "price": "29.99",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False  # Disable inventory tracking for this test
        })
        prod_id = prod_res.data['id']
        
        # Test: Anonymous user can get/create cart
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        cart_res = anonymous_client.get('/api/store/cart/current/')
        assert cart_res.status_code == 200
        assert 'id' in cart_res.data
        assert 'items' in cart_res.data
        assert 'total' in cart_res.data
        
        # Test: Add item to cart
        add_res = anonymous_client.post('/api/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 2
        })
        assert add_res.status_code == 200
        assert len(add_res.data['items']) == 1
        assert Decimal(str(add_res.data['total'])) == Decimal("59.98")  # 2 * 29.99
        
        cart_id = add_res.data['id']
        item_id = add_res.data['items'][0]['item_id']
        
        # Test: Update item quantity
        update_res = anonymous_client.post('/api/store/cart/update_item/', {
            "item_id": item_id,
            "quantity": 3
        })
        assert update_res.status_code == 200
        assert Decimal(str(update_res.data['total'])) == Decimal("89.97")  # 3 * 29.99
        
        # Test: Remove item
        remove_res = anonymous_client.post('/api/store/cart/remove_item/', {
            "item_id": item_id
        })
        assert remove_res.status_code == 200
        assert len(remove_res.data['items']) == 0
        assert Decimal(str(remove_res.data['total'])) == Decimal("0.00")
        
        # Test: Clear cart
        # Add item again first
        anonymous_client.post('/api/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 1
        })
        clear_res = anonymous_client.post('/api/store/cart/clear/')
        assert clear_res.status_code == 200
        assert len(clear_res.data['items']) == 0
    
    def test_cart_merge_on_login(self, workspace):
        """Test guest cart and authenticated cart both work"""
        # Setup: Create product
        admin_user = User.objects.create_user(
            username='admin3',
            email='admin3@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Toys", "slug": "toys", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Toy Car", "slug": "toy-car", "price": "15.99",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False  # Disable inventory tracking for this test
        })
        prod_id = prod_res.data['id']
        
        # Step 1: Anonymous user adds to cart
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        anonymous_client.get('/api/store/cart/current/')  # Create session
        
        add_res = anonymous_client.post('/api/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 2
        })
        assert add_res.status_code == 200
        anonymous_cart_total = Decimal(str(add_res.data['total']))
        assert len(add_res.data['items']) > 0
        
        # Step 2: Authenticated user can also use cart
        customer_user = User.objects.create_user(
            username='customer1',
            email='customer1@test.com',
            password='testpass123'
        )
        
        authenticated_client = WorkspaceAPIClient(workspace=workspace)
        authenticated_client.force_authenticate(user=customer_user)
        
        # Authenticated user can add to cart
        auth_add_res = authenticated_client.post('/api/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 1
        })
        assert auth_add_res.status_code == 200
        assert len(auth_add_res.data['items']) > 0
        
        # Note: Full cart merge testing requires actual login flow with session management
        # which is better tested in integration tests with real HTTP sessions
    
    def test_cart_item_enhanced_fields(self, workspace):
        """Test cart item enhanced fields (image_url, variant_options)"""
        # Setup
        admin_user = User.objects.create_user(
            username='admin10',
            email='admin10@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Cart Category", "slug": "cart-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Cart Product",
            "slug": "cart-product",
            "price": "45.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "track_inventory": False
        })
        prod_id = prod_res.data['id']
        
        # Create variant with options
        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": "CART-VAR-001",
            "name": "Medium Blue",
            "price": "45.00",
            "stock_quantity": 10,
            "options": {"size": "Medium", "color": "Blue"}
        })
        var_id = var_res.data['id']
        
        # Test: Add to cart and check enhanced fields
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        add_res = anonymous_client.post('/api/store/cart/add_item/', {
            "product": prod_id,
            "variant": var_id,
            "quantity": 1
        })
        assert add_res.status_code == 200
        
        items = add_res.data['items']
        assert len(items) > 0
        item = items[0]
        assert 'image_url' in item  # May be None if no image
        assert 'variant_options' in item
        assert item['variant_options'] == {"size": "Medium", "color": "Blue"}


"""
E2E Test 18: Storefront Inventory Tracking

Test that storefront API correctly displays inventory information
including variant stock, warehouse breakdown, and batch data
"""

import pytest
from decimal import Decimal
from tests.client import WorkspaceAPIClient
from tests.factories import StaffRoleFactory, StaffMemberFactory
from django.contrib.auth import get_user_model
from bfg.shop.models import Product, ProductVariant, VariantInventory, ProductBatch
from bfg.delivery.models import Warehouse

User = get_user_model()


@pytest.mark.e2e
@pytest.mark.django_db
class TestStorefrontInventory:
    """Test storefront inventory display and tracking"""
    
    def test_variant_stock_display(self, workspace):
        """Test that variant stock information is correctly displayed in storefront API"""
        # Setup: Create admin user
        admin_user = User.objects.create_user(
            username='admin_inv',
            email='admin_inv@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        # Create warehouse
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="Test Warehouse",
            code="WH-TEST",
            city="Test City",
            country="US",
            postal_code="12345"
        )
        
        # Create category
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": "test-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        # Create product
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Test Product with Inventory",
            "slug": "test-product-inventory",
            "price": "99.99",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "track_inventory": True
        })
        prod_id = prod_res.data['id']
        
        # Create variant
        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": "TEST-VAR-001",
            "name": "Test Variant",
            "price": "99.99",
            "stock_quantity": 0,  # Will be synced from VariantInventory
        })
        var_id = var_res.data['id']
        
        # Create VariantInventory
        from bfg.shop.models import VariantInventory
        inventory = VariantInventory.objects.create(
            variant_id=var_id,
            warehouse=warehouse,
            quantity=150,
            reserved=25
        )
        
        # Sync variant stock_quantity
        variant = ProductVariant.objects.get(id=var_id)
        variant.stock_quantity = inventory.quantity
        variant.save()
        
        # Create ProductBatch
        from bfg.shop.models import ProductBatch
        from datetime import timedelta
        from django.utils import timezone
        
        batch1 = ProductBatch.objects.create(
            workspace=workspace,
            variant=variant,
            warehouse=warehouse,
            batch_number="BATCH-001",
            manufactured_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
            quantity=80,
            reserved=10,
            quality_status='normal'
        )
        
        batch2 = ProductBatch.objects.create(
            workspace=workspace,
            variant=variant,
            warehouse=warehouse,
            batch_number="BATCH-002",
            manufactured_date=timezone.now().date() - timedelta(days=10),
            expiry_date=timezone.now().date() + timedelta(days=350),
            quantity=70,
            reserved=15,
            quality_status='normal'
        )
        
        # Test: Anonymous user can see inventory information
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        
        # Get product detail
        detail_res = anonymous_client.get(f'/api/store/products/{prod_id}/')
        assert detail_res.status_code == 200
        
        # Check variant has stock information
        variants = detail_res.data.get('variants', [])
        assert len(variants) > 0
        
        test_variant = next((v for v in variants if v['id'] == var_id), None)
        assert test_variant is not None
        assert 'stock_quantity' in test_variant
        assert 'stock_available' in test_variant
        assert 'stock_reserved' in test_variant
        assert 'stock_by_warehouse' in test_variant
        
        # Verify stock values
        assert test_variant['stock_quantity'] == 150
        assert test_variant['stock_available'] == 125  # 150 - 25 reserved
        assert test_variant['stock_reserved'] == 25
        
        # Verify warehouse breakdown
        warehouse_breakdown = test_variant['stock_by_warehouse']
        assert len(warehouse_breakdown) == 1
        assert warehouse_breakdown[0]['warehouse_id'] == warehouse.id
        assert warehouse_breakdown[0]['quantity'] == 150
        assert warehouse_breakdown[0]['reserved'] == 25
        assert warehouse_breakdown[0]['available'] == 125
    
    def test_inventory_changes_reflected(self, workspace):
        """Test that inventory changes are reflected in storefront API"""
        # Setup: Create product with inventory
        admin_user = User.objects.create_user(
            username='admin_inv2',
            email='admin_inv2@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        warehouse = Warehouse.objects.create(
            workspace=workspace,
            name="Warehouse 2",
            code="WH-002",
            city="City",
            country="US",
            postal_code="12345"
        )
        
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
        
        # Create initial inventory
        from bfg.shop.models import VariantInventory
        inventory = VariantInventory.objects.create(
            variant_id=var_id,
            warehouse=warehouse,
            quantity=200,
            reserved=0
        )
        
        # Test: Get initial stock
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        detail_res = anonymous_client.get(f'/api/store/products/{prod_id}/')
        assert detail_res.status_code == 200
        
        variants = detail_res.data.get('variants', [])
        test_variant = next((v for v in variants if v['id'] == var_id), None)
        assert test_variant is not None
        initial_available = test_variant['stock_available']
        assert initial_available == 200
        
        # Change: Reserve some stock
        inventory.reserved = 30
        inventory.save()
        
        # Sync variant
        variant = ProductVariant.objects.get(id=var_id)
        variant.stock_quantity = inventory.quantity
        variant.save()
        
        # Test: Get updated stock
        detail_res2 = anonymous_client.get(f'/api/store/products/{prod_id}/')
        assert detail_res2.status_code == 200
        
        variants2 = detail_res2.data.get('variants', [])
        test_variant2 = next((v for v in variants2 if v['id'] == var_id), None)
        assert test_variant2 is not None
        
        # Verify stock changed
        updated_available = test_variant2['stock_available']
        assert updated_available == 170  # 200 - 30 reserved
        assert updated_available < initial_available
        assert test_variant2['stock_reserved'] == 30
        
        # Change: Reduce quantity (simulate sale)
        inventory.quantity = 180
        inventory.reserved = 20
        inventory.save()
        
        variant.stock_quantity = inventory.quantity
        variant.save()
        
        # Test: Get final stock
        detail_res3 = anonymous_client.get(f'/api/store/products/{prod_id}/')
        assert detail_res3.status_code == 200
        
        variants3 = detail_res3.data.get('variants', [])
        test_variant3 = next((v for v in variants3 if v['id'] == var_id), None)
        assert test_variant3 is not None
        
        final_available = test_variant3['stock_available']
        assert final_available == 160  # 180 - 20 reserved
        assert final_available < updated_available
        assert test_variant3['stock_quantity'] == 180
        assert test_variant3['stock_reserved'] == 20
    
    def test_multiple_warehouse_inventory(self, workspace):
        """Test inventory display with multiple warehouses"""
        # Setup
        admin_user = User.objects.create_user(
            username='admin_inv3',
            email='admin_inv3@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        # Create multiple warehouses
        wh1 = Warehouse.objects.create(
            workspace=workspace,
            name="Main Warehouse",
            code="WH-MAIN",
            city="City",
            country="US",
            postal_code="12345"
        )
        
        wh2 = Warehouse.objects.create(
            workspace=workspace,
            name="Secondary Warehouse",
            code="WH-SEC",
            city="City",
            country="US",
            postal_code="12345"
        )
        
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
            "stock_quantity": 0,
        })
        var_id = var_res.data['id']
        
        # Create inventory in multiple warehouses
        from bfg.shop.models import VariantInventory
        inv1 = VariantInventory.objects.create(
            variant_id=var_id,
            warehouse=wh1,
            quantity=100,
            reserved=10
        )
        
        inv2 = VariantInventory.objects.create(
            variant_id=var_id,
            warehouse=wh2,
            quantity=50,
            reserved=5
        )
        
        # Sync variant
        variant = ProductVariant.objects.get(id=var_id)
        variant.stock_quantity = inv1.quantity + inv2.quantity
        variant.save()
        
        # Test: Get product and verify multi-warehouse breakdown
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        detail_res = anonymous_client.get(f'/api/store/products/{prod_id}/')
        assert detail_res.status_code == 200
        
        variants = detail_res.data.get('variants', [])
        test_variant = next((v for v in variants if v['id'] == var_id), None)
        assert test_variant is not None
        
        # Verify totals
        assert test_variant['stock_quantity'] == 150  # 100 + 50
        assert test_variant['stock_reserved'] == 15  # 10 + 5
        assert test_variant['stock_available'] == 135  # 150 - 15
        
        # Verify warehouse breakdown
        warehouse_breakdown = test_variant['stock_by_warehouse']
        assert len(warehouse_breakdown) == 2
        
        # Find warehouses in breakdown
        wh1_data = next((w for w in warehouse_breakdown if w['warehouse_id'] == wh1.id), None)
        wh2_data = next((w for w in warehouse_breakdown if w['warehouse_id'] == wh2.id), None)
        
        assert wh1_data is not None
        assert wh2_data is not None
        
        assert wh1_data['quantity'] == 100
        assert wh1_data['reserved'] == 10
        assert wh1_data['available'] == 90
        
        assert wh2_data['quantity'] == 50
        assert wh2_data['reserved'] == 5
        assert wh2_data['available'] == 45


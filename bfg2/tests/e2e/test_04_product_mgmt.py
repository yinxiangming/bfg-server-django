"""
E2E Test 04: Product Management
"""

import pytest
from decimal import Decimal
from bfg.shop.models import Product, ProductCategory, ProductVariant
from bfg.shop.services import ProductService

@pytest.mark.e2e
@pytest.mark.django_db
class TestProductManagement:
    
    def test_category_creation(self, authenticated_client, workspace):
        """Test category creation via API"""
        payload = {
            "name": "Electronics",
            "slug": "electronics",
            "language": "en"
        }
        
        response = authenticated_client.post('/api/v1/shop/categories/', payload)
        
        assert response.status_code == 201
        assert response.data['slug'] == "electronics"
        
    def test_product_creation(self, authenticated_client, workspace):
        """Test product and variant creation via API"""
        # 1. Create category
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": "Phones", "slug": "phones", "language": "en"
        })
        cat_id = cat_res.data['id']
        
        # 2. Create product
        prod_payload = {
            "name": "iPhone 15",
            "slug": "iphone-15",
            "sku": "IPHONE-15",
            "price": "999.00",
            "description": "Latest iPhone",
            "language": "en"
        }
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', prod_payload)
        if prod_res.status_code != 201:
            print(f"\n⚠️  Product creation failed with {prod_res.status_code}")
            print(f"Response: {prod_res.data}")
        assert prod_res.status_code == 201
        prod_id = prod_res.data['id']
        
        # 3. Create variants
        var_payload = {
            "product": prod_id,
            "sku": "IP15-BLK-128",
            "name": "Black 128GB",
            "price": "999.00",
            "options": {"color": "Black", "storage": "128GB"}
        }
        
        var_res = authenticated_client.post('/api/v1/shop/variants/', var_payload)
        assert var_res.status_code == 201
        assert var_res.data['sku'] == "IP15-BLK-128"
    
    def test_sales_channel_management(self, authenticated_client, workspace):
        """Test sales channel creation and product assignment"""
        # Create product first
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            'name': 'Apparel', 'slug': 'apparel', 'language': 'en'
        })
        assert cat_res.status_code == 201
        
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            'name': 'T-Shirt', 'slug': 't-shirt', 'price': '25.00', 'language': 'en'
        })
        assert prod_res.status_code == 201
        product_id = prod_res.data['id']
        
        # Create sales channel
        channel_res = authenticated_client.post('/api/v1/shop/sales-channels/', {
            'name': 'Mobile App',
            'code': 'MOBILE',
            'channel_type': 'mobile_app',
            'is_active': True
        })
        assert channel_res.status_code == 201
        channel_id = channel_res.data['id']
        
        # Add product to channel
        add_res = authenticated_client.post(
            f'/api/v1/shop/sales-channels/{channel_id}/add_product/',
            {'product_id': product_id}
        )
        assert add_res.status_code == 200
        assert add_res.data['success'] == True

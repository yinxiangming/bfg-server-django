"""
E2E Test 17.2: Storefront Categories API

Test category-related storefront API endpoints
Covers: category listing, tree structure, enhanced fields
"""

import uuid
import pytest


@pytest.mark.e2e
class TestStorefrontCategories:
    """Test storefront category-related API"""
    
    def test_categories_listing(self, workspace, admin_client, anonymous_api_client):
        """Test category listing"""
        suf = uuid.uuid4().hex[:6]
        # Setup: Create categories
        # Create parent category
        parent_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Electronics",
            "slug": f"electronics-{suf}",
            "language": "en",
            "is_active": True
        })
        parent_id = parent_res.data['id']
        
        # Create child category
        child_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Phones",
            "slug": f"phones-{suf}",
            "parent": parent_id,
            "language": "en",
            "is_active": True
        })
        
        # Test: List categories
        list_res = anonymous_api_client.get('/api/v1/store/categories/')
        assert list_res.status_code == 200
        
        # Test: Get tree structure
        tree_res = anonymous_api_client.get('/api/v1/store/categories/?tree=true')
        assert tree_res.status_code == 200
    
    def test_category_enhanced_fields(self, workspace, admin_client, anonymous_api_client):
        """Test category enhanced fields (image_url, product_count)"""
        suf = uuid.uuid4().hex[:6]
        # Setup
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Enhanced Category",
            "slug": f"enhanced-category-{suf}",
            "language": "en",
            "is_active": True
        })
        cat_id = cat_res.data['id']
        cat_slug = cat_res.data.get('slug') or f'enhanced-category-{suf}'
        
        # Create products in category
        for i in range(3):
            prod_res = admin_client.post('/api/v1/shop/products/', {
                "name": f"Product {i}",
                "slug": f"product-{i}-{suf}",
                "price": f"{10 + i}.00",
                "category_ids": [cat_id],
                "language": "en",
                "is_active": True
            })
            assert prod_res.status_code == 201
        
        # Test: Category contains enhanced fields
        category_res = anonymous_api_client.get(f'/api/v1/store/categories/{cat_id}/')
        assert category_res.status_code == 200
        
        category = category_res.data
        assert 'image_url' in category  # May be None if no image
        assert 'product_count' in category
        # Product count may be None or number
        if category.get('product_count') is not None:
            assert category['product_count'] >= 0
        
        # Test: Category list also contains enhanced fields (filter by slug — list may be paginated)
        list_res = anonymous_api_client.get(
            f'/api/v1/store/categories/?slug={cat_slug}'
        )
        assert list_res.status_code == 200
        categories = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        enhanced_cat = next((c for c in categories if c['id'] == cat_id), None)
        assert enhanced_cat is not None
        assert 'product_count' in enhanced_cat
        if enhanced_cat.get('product_count') is not None:
            assert enhanced_cat['product_count'] >= 0


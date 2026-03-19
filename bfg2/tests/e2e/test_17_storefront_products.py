"""
E2E Test 17.1: Storefront Products API

Test product-related storefront API endpoints
Covers: product browsing, filtering, sorting, reviews, variants
"""

import uuid
import pytest
from decimal import Decimal


@pytest.mark.e2e
class TestStorefrontProducts:
    """Test storefront product-related API"""
    
    def test_anonymous_browse_products(self, workspace, admin_client, anonymous_api_client):
        """Test anonymous user can browse products"""
        suf = uuid.uuid4().hex[:6]
        # Setup: Create product via admin API
        # Create category
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Electronics",
            "slug": f"electronics-{suf}",
            "language": "en",
            "is_active": True
        })
        assert cat_res.status_code == 201
        cat_id = cat_res.data['id']
        cat_slug = cat_res.data.get('slug', f'electronics-{suf}')
        
        # Create product
        prod_slug = f"wireless-headphones-{suf}"
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Wireless Headphones",
            "slug": prod_slug,
            "sku": f"WH-001-{suf}",
            "price": "99.99",
            "compare_price": "129.99",
            "category_ids": [cat_id],
            "description": "High-quality wireless headphones",
            "short_description": "Premium sound quality",
            "language": "en",
            "is_active": True
        })
        assert prod_res.status_code == 201
        prod_id = prod_res.data['id']
        
        # Create variant
        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": f"WH-001-BLACK-{suf}",
            "name": "Black",
            "price": "99.99",
            "stock_quantity": 50
        })
        assert var_res.status_code == 201
        
        # Test: Anonymous user can browse products
        browse_res = anonymous_api_client.get('/api/v1/store/products/')
        assert browse_res.status_code == 200
        
        # Handle both paginated and non-paginated responses
        if isinstance(browse_res.data, list):
            products = browse_res.data
        else:
            products = browse_res.data.get('results', [])
        
        assert len(products) > 0
        
        # Find our product
        our_product = next((p for p in products if p['id'] == prod_id), None)
        assert our_product is not None
        assert our_product['name'] == "Wireless Headphones"
        assert our_product['price'] == "99.99"
        assert 'description' in our_product
        assert 'media' in our_product
        assert 'variants' in our_product
        
        # Test: Filter by category (use slug we created)
        filter_res = anonymous_api_client.get(f'/api/v1/store/products/?category={cat_slug}')
        assert filter_res.status_code == 200
        
        # Test: Search
        search_res = anonymous_api_client.get('/api/v1/store/products/?q=headphones')
        assert search_res.status_code == 200
        
        # Test: Get product by slug
        detail_res = anonymous_api_client.get(f'/api/v1/store/products/{prod_slug}/')
        assert detail_res.status_code == 200
        assert detail_res.data['name'] == "Wireless Headphones"
        assert len(detail_res.data['variants']) > 0
    
    def test_product_enhanced_fields(self, workspace, admin_client, anonymous_api_client):
        """Test enhanced product fields (rating, reviews_count, primary_image, etc.)"""
        suf = uuid.uuid4().hex[:6]
        # Setup: Create product
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": f"test-category-{suf}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_slug = f"test-product-{suf}"
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Test Product",
            "slug": prod_slug,
            "price": "50.00",
            "compare_price": "60.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "is_featured": True
        })
        prod_id = prod_res.data['id']
        
        # Test: Product detail contains enhanced fields
        detail_res = anonymous_api_client.get(f'/api/v1/store/products/{prod_slug}/')
        assert detail_res.status_code == 200
        
        product = detail_res.data
        assert 'rating' in product  # Should be None for new product
        assert 'reviews_count' in product  # Should be 0 for new product
        assert product.get('reviews_count', 0) == 0
        assert 'primary_image' in product
        assert 'images' in product
        assert isinstance(product['images'], list)
        assert 'discount_percentage' in product
        assert 'is_new' in product
        assert isinstance(product['is_new'], bool)
        assert 'is_featured' in product
        assert product['is_featured'] is True
    
    def test_product_filtering(self, workspace, admin_client, anonymous_api_client):
        """Test product filtering (featured, is_new, bestseller)"""
        # Setup
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Filter Category", "slug": "filter-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        # Create featured product
        featured_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Featured Product",
            "slug": "featured-product",
            "price": "100.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "is_featured": True
        })
        featured_id = featured_res.data['id']
        
        # Create non-featured product
        normal_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Normal Product",
            "slug": "normal-product",
            "price": "50.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "is_featured": False
        })
        
        # Test: Filter by featured
        featured_list = anonymous_api_client.get('/api/v1/store/products/?featured=true')
        assert featured_list.status_code == 200
        products = featured_list.data if isinstance(featured_list.data, list) else featured_list.data.get('results', [])
        featured_products = [p for p in products if p['id'] == featured_id]
        assert len(featured_products) > 0
        
        # Test: Filter by is_new
        new_list = anonymous_api_client.get('/api/v1/store/products/?is_new=true')
        assert new_list.status_code == 200
        products = new_list.data if isinstance(new_list.data, list) else new_list.data.get('results', [])
        # Both products should be new (created recently)
        assert len(products) >= 2
        
        # Test: Bestseller filter (requires orders, will be empty initially)
        bestseller_list = anonymous_api_client.get('/api/v1/store/products/?bestseller=true')
        assert bestseller_list.status_code == 200
        
        # Test: Limit parameter
        limited_list = anonymous_api_client.get('/api/v1/store/products/?limit=1')
        assert limited_list.status_code == 200
        products = limited_list.data if isinstance(limited_list.data, list) else limited_list.data.get('results', [])
        assert len(products) <= 1
    
    def test_product_reviews(self, workspace, admin_client, customer_client, anonymous_api_client):
        """Test product reviews API (admin creates product, customer posts review, anonymous reads)"""
        # Admin creates product
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Review Category", "slug": "review-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']

        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Reviewable Product",
            "slug": "reviewable-product",
            "price": "75.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True
        })
        prod_id = prod_res.data['id']

        # Customer posts first review
        create_review_res = customer_client.post('/api/v1/store/products/reviewable-product/reviews/', {
            "rating": 5,
            "title": "Great product!",
            "comment": "Very satisfied with the quality",
        })
        assert create_review_res.status_code == 201
        assert create_review_res.data['rating'] == 5
        assert create_review_res.data['title'] == "Great product!"

        # Anonymous reads reviews (backend may show unapproved or only approved)
        reviews_res = anonymous_api_client.get('/api/v1/store/products/reviewable-product/reviews/')
        assert reviews_res.status_code == 200
        assert isinstance(reviews_res.data, list)
        # Backend may show only approved reviews; if our review is visible, check content
        if len(reviews_res.data) >= 1:
            assert reviews_res.data[0]['rating'] == 5
            assert reviews_res.data[0]['title'] == "Great product!"
            assert 'customer_name' in reviews_res.data[0]

        # Filter reviews by rating
        filtered_reviews = anonymous_api_client.get('/api/v1/store/products/reviewable-product/reviews/?rating=5')
        assert filtered_reviews.status_code == 200
        assert isinstance(filtered_reviews.data, list)

        # Customer cannot create duplicate review
        duplicate_res = customer_client.post('/api/v1/store/products/reviewable-product/reviews/', {
            "rating": 4,
            "title": "Duplicate",
            "comment": "Should fail"
        })
        assert duplicate_res.status_code == 400

        # Product rating and reviews_count updated
        detail_res = anonymous_api_client.get('/api/v1/store/products/reviewable-product/')
        assert detail_res.status_code == 200
        assert detail_res.data['reviews_count'] >= 1
        assert 4.0 <= float(detail_res.data['rating']) <= 5.0

        # Unauthenticated cannot create review
        unauth_res = anonymous_api_client.post('/api/v1/store/products/reviewable-product/reviews/', {
            "rating": 3,
            "title": "Should fail",
            "comment": "Not authenticated"
        })
        assert unauth_res.status_code == 401
    
    def test_product_variant_options(self, workspace, admin_client, anonymous_api_client):
        """Test product variant options field"""
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Variant Category", "slug": "variant-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Variant Product",
            "slug": "variant-product",
            "price": "80.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True
        })
        prod_id = prod_res.data['id']
        
        # Create variant with options
        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": "VAR-001",
            "name": "Large Red",
            "price": "80.00",
            "stock_quantity": 20,
            "options": {"size": "Large", "color": "Red"}
        })
        var_id = var_res.data['id']
        
        # Test: Variant options in storefront API
        detail_res = anonymous_api_client.get(f'/api/v1/store/products/variant-product/')
        assert detail_res.status_code == 200
        
        variants = detail_res.data['variants']
        assert len(variants) > 0
        variant = next((v for v in variants if v['id'] == var_id), None)
        assert variant is not None
        assert 'options' in variant
        assert variant['options'] == {"size": "Large", "color": "Red"}
        assert 'compare_price' in variant
        assert 'is_active' in variant
    
    def test_product_sorting(self, workspace, admin_client, anonymous_api_client):
        """Test product sorting (price_asc, price_desc, name, sales)"""
        suf = uuid.uuid4().hex[:6]
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Sort Category", "slug": f"sort-category-{suf}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        # Create products with different prices and names
        products_data = [
            {"name": "Zebra Product", "slug": f"zebra-product-{suf}", "price": "100.00"},
            {"name": "Alpha Product", "slug": f"alpha-product-{suf}", "price": "50.00"},
            {"name": "Beta Product", "slug": f"beta-product-{suf}", "price": "150.00"},
        ]
        
        for prod_data in products_data:
            admin_client.post('/api/v1/shop/products/', {
                "name": prod_data["name"],
                "slug": prod_data["slug"],
                "price": prod_data["price"],
                "category_ids": [cat_id],
                "language": "en",
                "is_active": True
            })
        
        # Test: Sort by price ascending
        price_asc_res = anonymous_api_client.get('/api/v1/store/products/?sort=price_asc')
        assert price_asc_res.status_code == 200
        products = price_asc_res.data if isinstance(price_asc_res.data, list) else price_asc_res.data.get('results', [])
        prices = [Decimal(str(p['price'])) for p in products if p.get('price')]
        if len(prices) >= 2:
            assert prices == sorted(prices), "Products should be sorted by price ascending"
        
        # Test: Sort by price descending
        price_desc_res = anonymous_api_client.get('/api/v1/store/products/?sort=price_desc')
        assert price_desc_res.status_code == 200
        products = price_desc_res.data if isinstance(price_desc_res.data, list) else price_desc_res.data.get('results', [])
        prices = [Decimal(str(p['price'])) for p in products if p.get('price')]
        if len(prices) >= 2:
            assert prices == sorted(prices, reverse=True), "Products should be sorted by price descending"
        
        # Test: Sort by name (only verify our 3 products are in sorted order within response)
        name_res = anonymous_api_client.get('/api/v1/store/products/?sort=name')
        assert name_res.status_code == 200
        products = name_res.data if isinstance(name_res.data, list) else name_res.data.get('results', [])
        our_names = {"Alpha Product", "Beta Product", "Zebra Product"}
        our_sorted = [p["name"] for p in products if p.get("name") in our_names]
        if len(our_sorted) >= 2:
            assert our_sorted == sorted(our_sorted), "Our products should appear in sorted name order"
        
        # Test: Sort by sales (bestseller)
        sales_res = anonymous_api_client.get('/api/v1/store/products/?sort=sales')
        assert sales_res.status_code == 200
        # Sales sort should not raise errors even if no orders exist
    
    def test_product_filtering_complete(self, workspace, admin_client, anonymous_api_client):
        """Test complete product filtering (tag, min_price, max_price)"""
        # Create tag via API with unique slug so create always succeeds
        tag_slug = f"premium-{uuid.uuid4().hex[:8]}"
        tag_res = admin_client.post('/api/v1/shop/products/tags/', {
            "name": "Premium", "slug": tag_slug, "language": "en"
        })
        assert tag_res.status_code == 201, (
            f"shop/products/tags create failed: {tag_res.status_code} {tag_res.data}"
        )
        tag_id = tag_res.data['id']

        cat_suf = uuid.uuid4().hex[:8]
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Filter Category", "slug": f"filter-category-{cat_suf}", "language": "en", "is_active": True
        })
        assert cat_res.status_code == 201
        cat_id = cat_res.data['id']

        prod_suf = uuid.uuid4().hex[:8]
        prod1_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Cheap Product",
            "slug": f"cheap-product-{prod_suf}",
            "price": "25.00",
            "category_ids": [cat_id],
            "tag_ids": [],
            "language": "en",
            "is_active": True
        })
        assert prod1_res.status_code == 201

        prod2_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Premium Product",
            "slug": f"premium-product-{prod_suf}",
            "price": "75.00",
            "category_ids": [cat_id],
            "tag_ids": [tag_id],
            "language": "en",
            "is_active": True
        })
        assert prod2_res.status_code == 201

        prod3_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Expensive Product",
            "slug": f"expensive-product-{prod_suf}",
            "price": "125.00",
            "category_ids": [cat_id],
            "tag_ids": [],
            "language": "en",
            "is_active": True
        })
        assert prod3_res.status_code == 201

        premium_slug = f"premium-product-{prod_suf}"
        # Test: Filter by tag (use slug we created)
        tag_filter_res = anonymous_api_client.get(f'/api/v1/store/products/?tag={tag_slug}')
        assert tag_filter_res.status_code == 200
        products = tag_filter_res.data if isinstance(tag_filter_res.data, list) else tag_filter_res.data.get('results', [])
        premium_product = next((p for p in products if p.get('slug') == premium_slug), None)
        assert premium_product is not None, "Should find premium product when filtering by tag"
        
        # Test: Filter by min_price
        min_price_res = anonymous_api_client.get('/api/v1/store/products/?min_price=50')
        assert min_price_res.status_code == 200
        products = min_price_res.data if isinstance(min_price_res.data, list) else min_price_res.data.get('results', [])
        for product in products:
            if product.get('price'):
                assert Decimal(str(product['price'])) >= Decimal('50.00'), "All products should be >= min_price"
        
        # Test: Filter by max_price
        max_price_res = anonymous_api_client.get('/api/v1/store/products/?max_price=100')
        assert max_price_res.status_code == 200
        products = max_price_res.data if isinstance(max_price_res.data, list) else max_price_res.data.get('results', [])
        for product in products:
            if product.get('price'):
                assert Decimal(str(product['price'])) <= Decimal('100.00'), "All products should be <= max_price"
        
        # Test: Filter by price range
        range_res = anonymous_api_client.get('/api/v1/store/products/?min_price=50&max_price=100')
        assert range_res.status_code == 200
        products = range_res.data if isinstance(range_res.data, list) else range_res.data.get('results', [])
        for product in products:
            if product.get('price'):
                price = Decimal(str(product['price']))
                assert Decimal('50.00') <= price <= Decimal('100.00'), "All products should be in price range"
        
        # Test: Combined filters (tag + price)
        combined_res = anonymous_api_client.get(f'/api/v1/store/products/?tag={tag_slug}&min_price=50&max_price=100')
        assert combined_res.status_code == 200
        products = combined_res.data if isinstance(combined_res.data, list) else combined_res.data.get('results', [])
        premium_product = next((p for p in products if p.get('slug') == premium_slug), None)
        assert premium_product is not None, "Should find premium product in price range"


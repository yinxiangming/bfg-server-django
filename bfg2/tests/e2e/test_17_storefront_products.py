"""
E2E Test 17.1: Storefront Products API

Test product-related storefront API endpoints
Covers: product browsing, filtering, sorting, reviews, variants
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from tests.client import WorkspaceAPIClient
from tests.factories import StaffRoleFactory, StaffMemberFactory

User = get_user_model()


@pytest.mark.e2e
@pytest.mark.django_db
class TestStorefrontProducts:
    """Test storefront product-related API"""
    
    def test_anonymous_browse_products(self, workspace):
        """Test anonymous user can browse products"""
        # Setup: Create product via admin API (using authenticated client)
        from rest_framework.test import APIClient
        
        # Create admin user with staff role
        admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        # Create category
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Electronics",
            "slug": "electronics",
            "language": "en",
            "is_active": True
        })
        assert cat_res.status_code == 201
        cat_id = cat_res.data['id']
        
        # Create product
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Wireless Headphones",
            "slug": "wireless-headphones",
            "sku": "WH-001",
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
            "sku": "WH-001-BLACK",
            "name": "Black",
            "price": "99.99",
            "stock_quantity": 50
        })
        assert var_res.status_code == 201
        
        # Test: Anonymous user can browse products
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        browse_res = anonymous_client.get('/api/store/products/')
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
        
        # Test: Filter by category
        filter_res = anonymous_client.get('/api/store/products/?category=electronics')
        assert filter_res.status_code == 200
        
        # Test: Search
        search_res = anonymous_client.get('/api/store/products/?q=headphones')
        assert search_res.status_code == 200
        
        # Test: Get product by slug
        detail_res = anonymous_client.get(f'/api/store/products/wireless-headphones/')
        assert detail_res.status_code == 200
        assert detail_res.data['name'] == "Wireless Headphones"
        assert len(detail_res.data['variants']) > 0
    
    def test_product_enhanced_fields(self, workspace):
        """Test enhanced product fields (rating, reviews_count, primary_image, etc.)"""
        # Setup: Create admin user and product
        admin_user = User.objects.create_user(
            username='admin5',
            email='admin5@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Test Category", "slug": "test-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Test Product",
            "slug": "test-product",
            "price": "50.00",
            "compare_price": "60.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "is_featured": True
        })
        prod_id = prod_res.data['id']
        
        # Test: Product detail contains enhanced fields
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        detail_res = anonymous_client.get(f'/api/store/products/test-product/')
        assert detail_res.status_code == 200
        
        product = detail_res.data
        assert 'rating' in product  # Should be None for new product
        assert 'reviews_count' in product  # Should be 0 for new product
        assert product['reviews_count'] == 0
        assert 'primary_image' in product
        assert 'images' in product
        assert isinstance(product['images'], list)
        assert 'discount_percentage' in product
        assert 'is_new' in product
        assert isinstance(product['is_new'], bool)
        assert 'is_featured' in product
        assert product['is_featured'] is True
    
    def test_product_filtering(self, workspace):
        """Test product filtering (featured, is_new, bestseller)"""
        # Setup
        admin_user = User.objects.create_user(
            username='admin6',
            email='admin6@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
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
        
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        
        # Test: Filter by featured
        featured_list = anonymous_client.get('/api/store/products/?featured=true')
        assert featured_list.status_code == 200
        products = featured_list.data if isinstance(featured_list.data, list) else featured_list.data.get('results', [])
        featured_products = [p for p in products if p['id'] == featured_id]
        assert len(featured_products) > 0
        
        # Test: Filter by is_new
        new_list = anonymous_client.get('/api/store/products/?is_new=true')
        assert new_list.status_code == 200
        products = new_list.data if isinstance(new_list.data, list) else new_list.data.get('results', [])
        # Both products should be new (created recently)
        assert len(products) >= 2
        
        # Test: Bestseller filter (requires orders, will be empty initially)
        bestseller_list = anonymous_client.get('/api/store/products/?bestseller=true')
        assert bestseller_list.status_code == 200
        
        # Test: Limit parameter
        limited_list = anonymous_client.get('/api/store/products/?limit=1')
        assert limited_list.status_code == 200
        products = limited_list.data if isinstance(limited_list.data, list) else limited_list.data.get('results', [])
        assert len(products) <= 1
    
    def test_product_reviews(self, workspace):
        """Test product reviews API"""
        # Setup: Create admin user, customer, and product
        admin_user = User.objects.create_user(
            username='admin7',
            email='admin7@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
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
        
        # Create customer user
        customer_user = User.objects.create_user(
            username='reviewer1',
            email='reviewer1@test.com',
            password='testpass123'
        )
        from bfg.common.models import Customer
        customer = Customer.objects.create(
            workspace=workspace,
            user=customer_user,
            is_active=True
        )
        
        # Create review via admin API (for testing GET)
        from bfg.shop.models import ProductReview
        review = ProductReview.objects.create(
            workspace=workspace,
            product_id=prod_id,
            customer=customer,
            rating=5,
            title="Great product!",
            comment="Very satisfied with the quality",
            is_approved=True
        )
        
        # Test: GET reviews (anonymous) - use slug since lookup_field is slug
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        reviews_res = anonymous_client.get('/api/store/products/reviewable-product/reviews/')
        assert reviews_res.status_code == 200
        assert isinstance(reviews_res.data, list)
        assert len(reviews_res.data) == 1
        assert reviews_res.data[0]['rating'] == 5
        assert reviews_res.data[0]['title'] == "Great product!"
        assert 'customer_name' in reviews_res.data[0]
        assert 'is_verified_purchase' in reviews_res.data[0]
        assert 'helpful_count' in reviews_res.data[0]
        assert 'images' in reviews_res.data[0]
        assert isinstance(reviews_res.data[0]['images'], list)
        
        # Test: Filter reviews by rating
        filtered_reviews = anonymous_client.get('/api/store/products/reviewable-product/reviews/?rating=5')
        assert filtered_reviews.status_code == 200
        assert len(filtered_reviews.data) == 1
        
        # Test: POST review (authenticated)
        customer_client = WorkspaceAPIClient(workspace=workspace)
        customer_client.force_authenticate(user=customer_user)
        
        # Create another customer for second review
        customer_user2 = User.objects.create_user(
            username='reviewer2',
            email='reviewer2@test.com',
            password='testpass123'
        )
        customer2 = Customer.objects.create(
            workspace=workspace,
            user=customer_user2,
            is_active=True
        )
        
        customer_client2 = WorkspaceAPIClient(workspace=workspace)
        customer_client2.force_authenticate(user=customer_user2)
        
        create_review_res = customer_client2.post('/api/store/products/reviewable-product/reviews/', {
            "rating": 4,
            "title": "Good product",
            "comment": "Pretty good, but could be better",
            "images": ["/media/reviews/test.jpg"]
        })
        assert create_review_res.status_code == 201
        assert create_review_res.data['rating'] == 4
        assert create_review_res.data['title'] == "Good product"
        # Images may be processed/transformed, so just check it's a list
        assert isinstance(create_review_res.data['images'], list)
        # Note: images field should be saved but may be processed differently
        
        # Test: Cannot create duplicate review
        duplicate_res = customer_client2.post('/api/store/products/reviewable-product/reviews/', {
            "rating": 5,
            "title": "Duplicate",
            "comment": "Should fail"
        })
        assert duplicate_res.status_code == 400
        
        # Test: Product rating and reviews_count updated
        # Note: New reviews require approval, so only the first approved review counts
        detail_res = anonymous_client.get('/api/store/products/reviewable-product/')
        assert detail_res.status_code == 200
        # Only approved reviews are counted (first review was approved, second needs approval)
        assert detail_res.data['reviews_count'] == 1
        assert detail_res.data['rating'] == 5.0
        
        # Approve the second review to test full functionality
        from bfg.shop.models import ProductReview
        new_review = ProductReview.objects.filter(
            product_id=prod_id,
            rating=4,
            customer=customer2
        ).first()
        if new_review:
            new_review.is_approved = True
            new_review.save()
            
            # Check again - should now have 2 reviews
            detail_res2 = anonymous_client.get('/api/store/products/reviewable-product/')
            assert detail_res2.data['reviews_count'] == 2
            assert detail_res2.data['rating'] == 4.5  # (5 + 4) / 2 = 4.5
        
        # Test: Unauthenticated cannot create review
        unauth_res = anonymous_client.post('/api/store/products/reviewable-product/reviews/', {
            "rating": 3,
            "title": "Should fail",
            "comment": "Not authenticated"
        })
        assert unauth_res.status_code == 401
    
    def test_product_variant_options(self, workspace):
        """Test product variant options field"""
        # Setup
        admin_user = User.objects.create_user(
            username='admin8',
            email='admin8@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
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
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        detail_res = anonymous_client.get(f'/api/store/products/variant-product/')
        assert detail_res.status_code == 200
        
        variants = detail_res.data['variants']
        assert len(variants) > 0
        variant = next((v for v in variants if v['id'] == var_id), None)
        assert variant is not None
        assert 'options' in variant
        assert variant['options'] == {"size": "Large", "color": "Red"}
        assert 'compare_price' in variant
        assert 'is_active' in variant
    
    def test_product_sorting(self, workspace):
        """Test product sorting (price_asc, price_desc, name, sales)"""
        # Setup
        admin_user = User.objects.create_user(
            username='admin11',
            email='admin11@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Sort Category", "slug": "sort-category", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        # Create products with different prices and names
        products_data = [
            {"name": "Zebra Product", "slug": "zebra-product", "price": "100.00"},
            {"name": "Alpha Product", "slug": "alpha-product", "price": "50.00"},
            {"name": "Beta Product", "slug": "beta-product", "price": "150.00"},
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
        
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        
        # Test: Sort by price ascending
        price_asc_res = anonymous_client.get('/api/store/products/?sort=price_asc')
        assert price_asc_res.status_code == 200
        products = price_asc_res.data if isinstance(price_asc_res.data, list) else price_asc_res.data.get('results', [])
        prices = [Decimal(str(p['price'])) for p in products if p.get('price')]
        if len(prices) >= 2:
            assert prices == sorted(prices), "Products should be sorted by price ascending"
        
        # Test: Sort by price descending
        price_desc_res = anonymous_client.get('/api/store/products/?sort=price_desc')
        assert price_desc_res.status_code == 200
        products = price_desc_res.data if isinstance(price_desc_res.data, list) else price_desc_res.data.get('results', [])
        prices = [Decimal(str(p['price'])) for p in products if p.get('price')]
        if len(prices) >= 2:
            assert prices == sorted(prices, reverse=True), "Products should be sorted by price descending"
        
        # Test: Sort by name
        name_res = anonymous_client.get('/api/store/products/?sort=name')
        assert name_res.status_code == 200
        products = name_res.data if isinstance(name_res.data, list) else name_res.data.get('results', [])
        names = [p['name'] for p in products if p.get('name')]
        if len(names) >= 2:
            assert names == sorted(names), "Products should be sorted by name"
        
        # Test: Sort by sales (bestseller)
        sales_res = anonymous_client.get('/api/store/products/?sort=sales')
        assert sales_res.status_code == 200
        # Sales sort should not raise errors even if no orders exist
    
    def test_product_filtering_complete(self, workspace):
        """Test complete product filtering (tag, min_price, max_price)"""
        # Setup
        admin_user = User.objects.create_user(
            username='admin12',
            email='admin12@test.com',
            password='testpass123'
        )
        role = StaffRoleFactory(workspace=workspace, code='admin', name='Administrator')
        StaffMemberFactory(workspace=workspace, user=admin_user, role=role)
        
        admin_client = WorkspaceAPIClient(workspace=workspace)
        admin_client.force_authenticate(user=admin_user)
        
        # Create tag using direct model creation (tag endpoint requires different structure)
        from bfg.shop.models import ProductTag
        tag, created = ProductTag.objects.get_or_create(
            workspace=workspace,
            slug="premium",
            language="en",
            defaults={"name": "Premium"}
        )
        tag_id = tag.id
        
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Filter Category", "slug": "filter-category-2", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        # Create products with different prices and tags
        prod1_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Cheap Product",
            "slug": "cheap-product",
            "price": "25.00",
            "category_ids": [cat_id],
            "tag_ids": [],
            "language": "en",
            "is_active": True
        })
        
        prod2_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Premium Product",
            "slug": "premium-product",
            "price": "75.00",
            "category_ids": [cat_id],
            "tag_ids": [tag_id],
            "language": "en",
            "is_active": True
        })
        
        prod3_res = admin_client.post('/api/v1/shop/products/', {
            "name": "Expensive Product",
            "slug": "expensive-product",
            "price": "125.00",
            "category_ids": [cat_id],
            "tag_ids": [],
            "language": "en",
            "is_active": True
        })
        
        anonymous_client = WorkspaceAPIClient(workspace=workspace)
        
        # Test: Filter by tag
        tag_filter_res = anonymous_client.get('/api/store/products/?tag=premium')
        assert tag_filter_res.status_code == 200
        products = tag_filter_res.data if isinstance(tag_filter_res.data, list) else tag_filter_res.data.get('results', [])
        premium_product = next((p for p in products if p['slug'] == 'premium-product'), None)
        assert premium_product is not None, "Should find premium product"
        
        # Test: Filter by min_price
        min_price_res = anonymous_client.get('/api/store/products/?min_price=50')
        assert min_price_res.status_code == 200
        products = min_price_res.data if isinstance(min_price_res.data, list) else min_price_res.data.get('results', [])
        for product in products:
            if product.get('price'):
                assert Decimal(str(product['price'])) >= Decimal('50.00'), "All products should be >= min_price"
        
        # Test: Filter by max_price
        max_price_res = anonymous_client.get('/api/store/products/?max_price=100')
        assert max_price_res.status_code == 200
        products = max_price_res.data if isinstance(max_price_res.data, list) else max_price_res.data.get('results', [])
        for product in products:
            if product.get('price'):
                assert Decimal(str(product['price'])) <= Decimal('100.00'), "All products should be <= max_price"
        
        # Test: Filter by price range
        range_res = anonymous_client.get('/api/store/products/?min_price=50&max_price=100')
        assert range_res.status_code == 200
        products = range_res.data if isinstance(range_res.data, list) else range_res.data.get('results', [])
        for product in products:
            if product.get('price'):
                price = Decimal(str(product['price']))
                assert Decimal('50.00') <= price <= Decimal('100.00'), "All products should be in price range"
        
        # Test: Combined filters (tag + price)
        combined_res = anonymous_client.get('/api/store/products/?tag=premium&min_price=50&max_price=100')
        assert combined_res.status_code == 200
        products = combined_res.data if isinstance(combined_res.data, list) else combined_res.data.get('results', [])
        premium_product = next((p for p in products if p['slug'] == 'premium-product'), None)
        assert premium_product is not None, "Should find premium product in price range"


# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.shop module.
"""

from decimal import Decimal
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from .models import (
    ProductCategory, Product, Store, Order, OrderItem,
    SalesChannel, ProductChannelListing, ChannelCollection, Return, ReturnLineItem,
    ProductTag, ProductVariant, ProductReview, Cart, CartItem, VariantInventory,
    ProductBatch, BatchMovement, SubscriptionPlan
)
from bfg.common.models import Address, Customer, Media, MediaLink


def clear_data():
    """Clear shop module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order
    BatchMovement.objects.all().delete()
    ProductBatch.objects.all().delete()
    VariantInventory.objects.all().delete()
    CartItem.objects.all().delete()
    Cart.objects.all().delete()
    ReturnLineItem.objects.all().delete()
    Return.objects.all().delete()
    ProductChannelListing.objects.all().delete()
    ChannelCollection.objects.all().delete()
    SalesChannel.objects.all().delete()
    # Delete MediaLinks for products (via GenericForeignKey)
    product_content_type = ContentType.objects.get_for_model(Product)
    MediaLink.objects.filter(content_type=product_content_type).delete()
    OrderItem.objects.all().delete()
    Order.objects.all().delete()
    ProductReview.objects.all().delete()
    ProductVariant.objects.all().delete()
    Product.objects.all().delete()
    ProductTag.objects.all().delete()
    ProductCategory.objects.all().delete()
    Store.objects.all().delete()
    SubscriptionPlan.objects.all().delete()
    # 3. Invalidate caches (none for shop)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed shop module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (admin_user, customer_users, customers, addresses, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating shop module data...'))
    
    admin_user = context.get('admin_user')
    customer_users = context.get('customer_users', [])
    customers = context.get('customers', [])
    addresses = context.get('addresses', [])
    
    # Create product categories
    categories = create_product_categories(workspace, stdout, style)
    
    # Create product tags
    tags = create_product_tags(workspace, stdout, style)
    
    # Create store
    store = create_store(workspace, stdout, style)
    
    # Create products
    products = create_products(workspace, categories, tags, admin_user, stdout, style)
    
    # Create product variants
    variants = create_product_variants(workspace, products, stdout, style)
    
    # Create product media (before inventory to ensure images are set)
    create_product_media(workspace, products, stdout, style)
    
    # Create variant inventory (before syncing product stock)
    create_variant_inventory(workspace, variants, stdout, style)
    
    # Sync product SKU and stock_quantity from variants
    sync_product_sku_and_stock(workspace, products, variants, stdout, style)
    
    # Create sales channels
    channels = create_sales_channels(workspace, stdout, style)
    create_channel_listings(workspace, products, categories, channels, stdout, style)
    
    # Create orders (after customers are created)
    orders = create_orders(workspace, customer_users, customers, addresses, store, products, stdout, style)
    
    # Create product reviews
    reviews = create_product_reviews(workspace, products, customers, stdout, style)
    
    # Create returns
    returns = create_returns(workspace, orders, customers, stdout, style)
    
    # Create carts
    carts = create_carts(workspace, customer_users, products, variants, stdout, style)
    
    # Create product batches
    batches = create_product_batches(workspace, products, variants, stdout, style)
    
    # Create subscription plans
    subscription_plans = create_subscription_plans(workspace, stdout, style)
    
    # Create order notification templates
    templates = create_order_notification_templates(workspace, stdout, style)
    
    summary = [
        {'label': 'Orders', 'count': Order.objects.count()},
    ]
    return {
        'categories': categories,
        'tags': tags,
        'store': store,
        'products': products,
        'variants': variants,
        'channels': channels,
        'orders': orders,
        'reviews': reviews,
        'returns': returns,
        'carts': carts,
        'batches': batches,
        'subscription_plans': subscription_plans,
        'templates': templates,
        'summary': summary,
    }


def create_product_categories(workspace, stdout=None, style=None):
    """Create product categories matching storefront frontend"""
    # Define categories matching frontend HomePage categories
    # Format: {'name': str, 'slug': str, 'parent_slug': str or None, 'order': int, 'icon': str, 'description': str, 'image_path': str}
    categories_data = [
        # Top-level categories matching frontend
        {'name': 'Clothes', 'slug': 'clothes', 'parent_slug': None, 'order': 1, 'icon': 'tabler-shirt', 'description': 'Clothing and apparel for all', 'image_path': 'categories/3-cp_categorylist.jpg'},
        {'name': 'Bag', 'slug': 'bag', 'parent_slug': None, 'order': 2, 'icon': 'tabler-briefcase', 'description': 'Bags and luggage', 'image_path': 'categories/6-cp_categorylist.jpg'},
        {'name': 'Shoes', 'slug': 'shoes', 'parent_slug': None, 'order': 3, 'icon': 'tabler-shoe', 'description': 'Footwear for all occasions', 'image_path': 'categories/9-cp_categorylist.jpg'},
        {'name': 'Shorts', 'slug': 'shorts', 'parent_slug': None, 'order': 4, 'icon': 'tabler-shirt', 'description': 'Shorts and casual wear', 'image_path': 'categories/10-cp_categorylist.jpg'},
        {'name': 'Cap', 'slug': 'cap', 'parent_slug': None, 'order': 5, 'icon': 'tabler-hat', 'description': 'Caps and hats', 'image_path': 'categories/11-cp_categorylist.jpg'},
        {'name': 'Watch', 'slug': 'watch', 'parent_slug': None, 'order': 6, 'icon': 'tabler-clock', 'description': 'Watches and timepieces', 'image_path': 'categories/12-cp_categorylist.jpg'},
        {'name': 'Belt', 'slug': 'belt', 'parent_slug': None, 'order': 7, 'icon': 'tabler-belt', 'description': 'Belts and accessories', 'image_path': 'categories/13-cp_categorylist.jpg'},
        {'name': 'Gogals', 'slug': 'gogals', 'parent_slug': None, 'order': 8, 'icon': 'tabler-sunglasses', 'description': 'Sunglasses and eyewear', 'image_path': 'categories/14-cp_categorylist.jpg'},
        
        # Clothes subcategories (matching frontend header)
        {'name': "Men's", 'slug': 'mens', 'parent_slug': 'clothes', 'order': 1, 'icon': 'tabler-user', 'description': "Men's clothing"},
        {'name': "Women's", 'slug': 'womens', 'parent_slug': 'clothes', 'order': 2, 'icon': 'tabler-user', 'description': "Women's clothing"},
        {'name': "Kids'", 'slug': 'kids', 'parent_slug': 'clothes', 'order': 3, 'icon': 'tabler-baby', 'description': "Kids' clothing"},
        {'name': 'Sports', 'slug': 'sports', 'parent_slug': 'clothes', 'order': 4, 'icon': 'tabler-ball-football', 'description': 'Sports clothing'},
        
        # Men's subcategories
        {'name': 'Formal Shirts', 'slug': 'formal-shirts', 'parent_slug': 'mens', 'order': 1, 'icon': 'tabler-shirt', 'description': "Men's formal shirts"},
        {'name': 'Formal Trousers', 'slug': 'formal-trousers', 'parent_slug': 'mens', 'order': 2, 'icon': 'tabler-shirt', 'description': "Men's formal trousers"},
        {'name': 'Hat', 'slug': 'mens-hat', 'parent_slug': 'mens', 'order': 3, 'icon': 'tabler-hat', 'description': "Men's hats"},
        {'name': 'Loungewear', 'slug': 'loungewear', 'parent_slug': 'mens', 'order': 4, 'icon': 'tabler-shirt', 'description': "Men's loungewear"},
        {'name': 'Formal Accessories', 'slug': 'formal-accessories', 'parent_slug': 'mens', 'order': 5, 'icon': 'tabler-accessory', 'description': "Men's formal accessories"},
        
        # Women's subcategories
        {'name': 'Jackets & Coats', 'slug': 'jackets-coats', 'parent_slug': 'womens', 'order': 1, 'icon': 'tabler-shirt', 'description': "Women's jackets and coats"},
        {'name': 'Shirts', 'slug': 'womens-shirts', 'parent_slug': 'womens', 'order': 2, 'icon': 'tabler-shirt', 'description': "Women's shirts"},
        {'name': 'Jumpers & Knitwear', 'slug': 'jumpers-knitwear', 'parent_slug': 'womens', 'order': 3, 'icon': 'tabler-shirt', 'description': "Women's jumpers and knitwear"},
        {'name': 'Pyjamas & Nightwear', 'slug': 'pyjamas-nightwear', 'parent_slug': 'womens', 'order': 4, 'icon': 'tabler-shirt', 'description': "Women's pyjamas and nightwear"},
        {'name': 'Jeans', 'slug': 'womens-jeans', 'parent_slug': 'womens', 'order': 5, 'icon': 'tabler-shirt', 'description': "Women's jeans"},
    ]
    
    categories = []
    category_map = {}  # Map slug to category object for parent lookup
    
    # First pass: create all categories without parent
    for cat_data in categories_data:
        parent = None
        if cat_data['parent_slug']:
            parent = category_map.get(cat_data['parent_slug'])
        
        category, created = ProductCategory.objects.get_or_create(
            workspace=workspace,
            slug=cat_data['slug'],
            language='en',
            defaults={
                'name': cat_data['name'],
                'description': cat_data.get('description', ''),
                'parent': parent,
                'order': cat_data['order'],
                'icon': cat_data.get('icon', ''),
                'is_active': True,
            }
        )
        
        # Update parent if category already existed but parent was None
        if not created and not category.parent and parent:
            category.parent = parent
            category.save()
        
        # Update order and icon if they changed
        if category.order != cat_data['order'] or category.icon != cat_data.get('icon', ''):
            category.order = cat_data['order']
            category.icon = cat_data.get('icon', '')
            category.save()
        
        # Set category image if image_path is provided
        if cat_data.get('image_path') and not category.image:
            # Use external_url approach for seed images
            # The image will be served from media/seed_images/store/{image_path}
            # We'll set it via external_url or handle it in serializer
            pass  # Image handling can be done via serializer or admin
        
        category_map[cat_data['slug']] = category
        categories.append(category)
        
        if created and stdout:
            parent_name = f" (parent: {parent.name})" if parent else ""
            stdout.write(style.SUCCESS(f'✓ Created product category: {category.name}{parent_name}'))
    
    return categories


def create_store(workspace, stdout=None, style=None):
    """Create store"""
    store, created = Store.objects.get_or_create(
        workspace=workspace,
        code='MAIN-STORE',
        defaults={
            'name': 'Main Store',
            'is_active': True,
        }
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created store: {store.name}'))
    return store


def create_products(workspace, categories, tags, admin_user, stdout=None, style=None):
    """Create products matching storefront frontend"""
    # Find categories by slug
    category_map = {cat.slug: cat for cat in categories}
    
    products_data = [
        {
            'name': "Nike men's air force 1",
            'slug': 'nike-mens-air-force-1',
            'price': Decimal('23.90'),
            'compare_price': None,
            'description': 'Classic Nike Air Force 1 sneakers for men. Timeless design with premium materials.',
            'short_description': 'Classic Nike Air Force 1 sneakers',
            'category_slug': 'shoes',
            'image_paths': ['nike-men-s-air-force-1.jpg'],
            'tags': ['new-arrival'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Daniel wellington oxford watch',
            'slug': 'daniel-wellington-oxford-watch',
            'price': Decimal('64.00'),
            'compare_price': Decimal('80.00'),
            'description': 'Elegant Daniel Wellington Oxford watch with classic design and premium quality.',
            'short_description': 'Elegant Daniel Wellington watch',
            'category_slug': 'watch',
            'image_paths': ['daniel-wellington-oxford-watch.jpg', 'daniel-wellington-oxford-watch-2.jpg'],
            'tags': ['new-arrival', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Boundaries women's tote bag",
            'slug': 'boundaries-womens-tote-bag',
            'price': Decimal('40.50'),
            'compare_price': Decimal('45.00'),
            'description': 'Stylish tote bag for women. Spacious and fashionable design perfect for everyday use.',
            'short_description': 'Stylish women tote bag',
            'category_slug': 'bag',
            'image_paths': ['boundaries-women-s-tote-bag.jpg'],
            'tags': ['sale', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Jeans shorts women's summer",
            'slug': 'jeans-shorts-womens-summer',
            'price': Decimal('35.00'),
            'compare_price': None,
            'description': 'Comfortable denim shorts perfect for summer. Available in multiple sizes and colors.',
            'short_description': 'Summer denim shorts',
            'category_slug': 'shorts',
            'image_paths': ['jeans-shorts-women-s-summer.jpg'],
            'tags': ['new-arrival'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Buckner leather backpack',
            'slug': 'buckner-leather-backpack',
            'price': Decimal('45.00'),
            'compare_price': None,
            'description': 'Premium leather backpack with multiple compartments. Durable and stylish.',
            'short_description': 'Premium leather backpack',
            'category_slug': 'bag',
            'image_paths': ['buckner-leather-backpack.jpg'],
            'tags': ['featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Classic men's warm winter cap",
            'slug': 'classic-mens-warm-winter-cap',
            'price': Decimal('25.00'),
            'compare_price': None,
            'description': 'Warm and comfortable winter cap for men. Perfect for cold weather.',
            'short_description': 'Warm winter cap',
            'category_slug': 'cap',
            'image_paths': ['classic-men-s-warm-winter-cap.jpg'],
            'tags': ['new-arrival'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Specs the prince sunglasses',
            'slug': 'specs-the-prince-sunglasses',
            'price': Decimal('41.00'),
            'compare_price': Decimal('50.00'),
            'description': 'Stylish sunglasses with UV protection. Classic design for all occasions.',
            'short_description': 'Stylish sunglasses',
            'category_slug': 'gogals',
            'image_paths': ['specs-the-prince-sunglasses.jpg'],
            'tags': ['sale', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Women's black color buckle solid",
            'slug': 'womens-black-color-buckle-solid',
            'price': Decimal('65.00'),
            'compare_price': None,
            'description': 'Elegant black belt with solid buckle. Perfect accessory for formal wear.',
            'short_description': 'Black belt with buckle',
            'category_slug': 'belt',
            'image_paths': ['women-s-black-color-buckle-solid.jpg'],
            'tags': ['featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Natural uniforms women's t-shirt",
            'slug': 'natural-uniforms-womens-t-shirt',
            'price': Decimal('52.00'),
            'compare_price': None,
            'description': 'Comfortable cotton t-shirt for women. Soft fabric and relaxed fit.',
            'short_description': 'Comfortable cotton t-shirt',
            'category_slug': 'clothes',
            'image_paths': ['natural-uniforms-women-s-t-shirt.jpg'],
            'tags': ['new-arrival'] if tags else [],
            'is_featured': False,
            'track_inventory': True,
        },
        {
            'name': 'Hush puppies sarah trim buckle',
            'slug': 'hush-puppies-sarah-trim-buckle',
            'price': Decimal('58.00'),
            'compare_price': None,
            'description': 'Classic Hush Puppies shoes with trim buckle design. Comfortable and stylish.',
            'short_description': 'Classic Hush Puppies shoes',
            'category_slug': 'shoes',
            'image_paths': ['hush-puppies-sarah-trim-buckle.jpg'],
            'tags': ['featured'] if tags else [],
            'is_featured': False,
            'track_inventory': True,
        },
        {
            'name': 'Tartine et Chocolat Cardigan Beige',
            'slug': 'tartine-et-chocolat-cardigan-beige',
            'price': Decimal('75.00'),
            'compare_price': Decimal('90.00'),
            'description': 'Elegant beige cardigan from Tartine et Chocolat. Soft and warm.',
            'short_description': 'Elegant beige cardigan',
            'category_slug': 'clothes',
            'image_paths': ['tartine-et-chocolat-cardigan-beige.jpg'],
            'tags': ['new-arrival', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'MVMT Boulevard Beverly Watch',
            'slug': 'mvmt-boulevard-beverly-watch',
            'price': Decimal('89.00'),
            'compare_price': Decimal('120.00'),
            'description': 'Stylish MVMT Boulevard Beverly watch with modern design.',
            'short_description': 'Modern MVMT watch',
            'category_slug': 'watch',
            'image_paths': ['mvmt-boulevard-beverly-watch.jpg'],
            'tags': ['sale', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Lauren Packable Down Puffer Jacket',
            'slug': 'lauren-packable-down-puffer-jacket',
            'price': Decimal('95.00'),
            'compare_price': None,
            'description': 'Warm and packable down puffer jacket. Perfect for winter.',
            'short_description': 'Packable puffer jacket',
            'category_slug': 'clothes',
            'image_paths': ['lauren-packable-down-puffer-jacket.jpg'],
            'tags': ['new-arrival'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Time and Tru Women's Lug Sole",
            'slug': 'time-and-tru-womens-lug-sole',
            'price': Decimal('65.00'),
            'compare_price': Decimal('80.00'),
            'description': 'Comfortable lug sole shoes for women. Durable and stylish.',
            'short_description': 'Women lug sole shoes',
            'category_slug': 'shoes',
            'image_paths': ['time-and-tru-women-s-lug-sole.jpg'],
            'tags': ['sale'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Black Women Solid Casual Belt',
            'slug': 'black-women-solid-casual-belt',
            'price': Decimal('35.00'),
            'compare_price': None,
            'description': 'Classic black casual belt for women. Versatile and elegant.',
            'short_description': 'Black casual belt',
            'category_slug': 'belt',
            'image_paths': ['black-women-solid-casual-belt.jpg'],
            'tags': ['featured'] if tags else [],
            'is_featured': False,
            'track_inventory': True,
        },
        {
            'name': 'Tru Brushed Herringbone Shacket',
            'slug': 'tru-brushed-herringbone-shacket',
            'price': Decimal('85.00'),
            'compare_price': Decimal('100.00'),
            'description': 'Stylish brushed herringbone shacket. Perfect for layering.',
            'short_description': 'Herringbone shacket',
            'category_slug': 'clothes',
            'image_paths': ['tru-brushed-herringbone-shacket.jpg'],
            'tags': ['sale', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Platform with Zipper Sneaker',
            'slug': 'platform-with-zipper-sneaker',
            'price': Decimal('55.00'),
            'compare_price': None,
            'description': 'Trendy platform sneakers with zipper detail. Modern and comfortable.',
            'short_description': 'Platform zipper sneakers',
            'category_slug': 'shoes',
            'image_paths': ['platform-with-zipper-sneaker.jpg'],
            'tags': ['new-arrival'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Nation Girls Fashion Flare Jeggings",
            'slug': 'nation-girls-fashion-flare-jeggings',
            'price': Decimal('42.00'),
            'compare_price': Decimal('50.00'),
            'description': 'Fashionable flare jeggings for girls. Comfortable and stylish.',
            'short_description': 'Flare jeggings',
            'category_slug': 'clothes',
            'image_paths': ['nation-girls-fashion-flare-jeggings.jpg'],
            'tags': ['sale'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': 'Women Short Sleeve Silk T-Shirt',
            'slug': 'women-short-sleeve-silk-t-shirt',
            'price': Decimal('48.00'),
            'compare_price': None,
            'description': 'Luxurious silk t-shirt for women. Soft and elegant.',
            'short_description': 'Silk t-shirt',
            'category_slug': 'clothes',
            'image_paths': ['women-short-sleeve-silk-t-shirt.jpg'],
            'tags': ['new-arrival', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
        {
            'name': "Men's Corduroy Vintage Polo Shirts",
            'slug': 'mens-corduroy-vintage-polo-shirts',
            'price': Decimal('52.00'),
            'compare_price': Decimal('65.00'),
            'description': 'Vintage style corduroy polo shirts for men. Classic and comfortable.',
            'short_description': 'Corduroy polo shirts',
            'category_slug': 'clothes',
            'image_paths': ['men-s-corduroy-vintage-polo-shirts.jpg'],
            'tags': ['sale', 'featured'] if tags else [],
            'is_featured': True,
            'track_inventory': True,
        },
    ]
    products = []
    for prod_data in products_data:
        # Get category by slug
        category = category_map.get(prod_data.get('category_slug'))
        
        product, created = Product.objects.get_or_create(
            workspace=workspace,
            slug=prod_data['slug'],
            defaults={
                'name': prod_data['name'],
                'price': prod_data['price'],
                'compare_price': prod_data.get('compare_price'),
                'description': prod_data.get('description', ''),
                'short_description': prod_data.get('short_description', ''),
                'language': 'en',
                'is_active': True,
                'is_featured': prod_data.get('is_featured', False),
                'track_inventory': prod_data.get('track_inventory', True),
            }
        )
        
        # Update is_featured if changed
        if not created and product.is_featured != prod_data.get('is_featured', False):
            product.is_featured = prod_data.get('is_featured', False)
            product.save()
        
        # Add category
        if category:
            product.categories.add(category)
        
        # Add tags
        if prod_data.get('tags'):
            for tag_slug in prod_data['tags']:
                tag = next((t for t in tags if t.slug == tag_slug), None)
                if tag:
                    product.tags.add(tag)
        
        # Store image_paths for later use in create_product_media
        if created:
            product._image_paths = prod_data.get('image_paths', [])
        elif not hasattr(product, '_image_paths'):
            product._image_paths = prod_data.get('image_paths', [])
        
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created product: {product.name}'))
        products.append(product)
    return products


def create_orders(workspace, customer_users, customers, addresses, store, products, stdout=None, style=None):
    """Create orders with order items"""
    from django.contrib.contenttypes.models import ContentType
    from bfg.common.models import Customer as CustomerModel
    
    if not products:
        if stdout:
            stdout.write(style.WARNING('⚠️  No products available, skipping order creation'))
        return []
    
    if not store:
        if stdout:
            stdout.write(style.WARNING('⚠️  No store available, skipping order creation'))
        return []
    
    # Always query customers from database to ensure we get them
    # Use provided customers if available, otherwise query all customers in workspace
    if customers:
        # If customers is a list, convert to queryset
        if isinstance(customers, list):
            customer_ids = [c.id if hasattr(c, 'id') else c for c in customers]
            customers_qs = CustomerModel.objects.filter(
                workspace=workspace,
                id__in=customer_ids
            )
        else:
            # Assume it's a queryset
            customers_qs = customers.filter(workspace=workspace) if hasattr(customers, 'filter') else customers
    else:
        # Query all customers in workspace
        customers_qs = CustomerModel.objects.filter(workspace=workspace)
        if customer_users:
            # If customer_users provided, filter by them
            customers_qs = customers_qs.filter(user__in=customer_users)
    
    # Check if we have any customers
    customers_count = customers_qs.count()
    if customers_count == 0:
        if stdout:
            stdout.write(style.WARNING('⚠️  No customers available in workspace, skipping order creation'))
        return []
    
    # Get addresses if not provided
    if not addresses:
        customer_content_type = ContentType.objects.get_for_model(CustomerModel)
        addresses = Address.objects.filter(
            workspace=workspace,
            content_type=customer_content_type
        )
    
    orders = []
    customer_list = list(customers_qs[:3])  # Limit to first 3 customers
    
    if stdout:
        stdout.write(style.SUCCESS(f'📦 Found {customers_count} customer(s), creating orders for {len(customer_list)} customer(s)'))
    
    for i, customer in enumerate(customer_list, 1):
        # Get customer addresses
        customer_content_type = ContentType.objects.get_for_model(CustomerModel)
        customer_addresses = Address.objects.filter(
            workspace=workspace,
            content_type=customer_content_type,
            object_id=customer.id
        )
        
        shipping_addr = customer_addresses.first()
        billing_addr = customer_addresses.last() if customer_addresses.count() > 1 else shipping_addr
        
        # Create address if none exists
        if not shipping_addr:
            shipping_addr = Address.objects.create(
                workspace=workspace,
                content_type=customer_content_type,
                object_id=customer.id,
                full_name=customer.user.get_full_name() or customer.user.username,
                phone=customer.user.phone or '+1-555-0000',
                email=customer.user.email or 'customer@example.com',
                address_line1=f'{100 + i} Main Street',
                city='New York',
                state='NY',
                postal_code='10001',
                country='US',
            )
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created shipping address for customer {customer}'))
        
        if not billing_addr:
            billing_addr = shipping_addr
        
        # Generate unique order number
        order_number = f'ORD-{timezone.now().strftime("%Y%m%d")}-{i:04d}'
        
        # Check if order already exists with different number
        existing_order = Order.objects.filter(
            workspace=workspace,
            customer=customer,
            store=store
        ).first()
        
        if existing_order:
            if stdout:
                stdout.write(style.WARNING(f'↻ Order already exists for customer {customer}: {existing_order.order_number}'))
            orders.append(existing_order)
            continue
        
        try:
            order, created = Order.objects.get_or_create(
                workspace=workspace,
                order_number=order_number,
                defaults={
                    'customer': customer,
                    'store': store,
                    'status': 'pending',
                    'payment_status': 'pending',
                    'subtotal': Decimal('0.00'),  # Will be calculated
                    'shipping_cost': Decimal('10.00'),
                    'tax': Decimal('0.00'),
                    'discount': Decimal('0.00'),
                    'total': Decimal('0.00'),  # Will be calculated
                    'shipping_address': shipping_addr,
                    'billing_address': billing_addr,
                }
            )
            if created:
                # Add order items with product association
                order_items = []
                subtotal = Decimal('0.00')
                for j, product in enumerate(products[:2], 1):
                    quantity = j
                    item_subtotal = product.price * quantity
                    order_item = OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price=product.price,
                        subtotal=item_subtotal,
                        product_name=product.name,
                        sku=product.sku or '',
                    )
                    order_items.append(order_item)
                    subtotal += item_subtotal
                
                # Update order totals based on actual order items
                shipping_cost = Decimal('10.00')
                tax = Decimal('0.00')
                discount = Decimal('0.00')
                total = subtotal + shipping_cost + tax - discount
                
                order.subtotal = subtotal
                order.shipping_cost = shipping_cost
                order.tax = tax
                order.discount = discount
                order.total = total
                order.save()
                
                orders.append(order)
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created order: {order.order_number} with {len(order_items)} items'))
            else:
                orders.append(order)
        except IntegrityError as e:
            if stdout:
                stdout.write(style.ERROR(f'✗ Failed to create order {order_number}: {str(e)}'))
            continue
    
    if stdout and not orders:
        stdout.write(style.WARNING('⚠️  No orders were created'))
    
    return orders


def create_product_media(workspace, products, stdout=None, style=None):
    """Create product media from seed_images directory.

    Image source (read): {MEDIA_ROOT}/seed_images/store/{image_path}
    - image_path comes from product._image_paths (e.g. 'nike-men-s-air-force-1.jpg' or
      'categories/3-cp_categorylist.jpg'). Files live under seed_images/store/ (flat for
      products; categories in seed_images/store/categories/).
    - Run `manage.py seed_data --copy-images` to copy bfg2/seed_media into media/seed_images
      so these paths resolve. Set BFG_SEED_MEDIA_ROOT if bfg is installed outside the repo.

    Image save (write): files are copied to {MEDIA_ROOT}/{workspace_id}/products/{filename},
    and Media records store the relative path '{workspace_id}/products/{filename}' (same as
    normal uploads). MediaLink links each Media to the Product.
    """
    import os
    import shutil
    from django.conf import settings
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    # Get admin user for uploaded_by
    admin_user = User.objects.filter(is_superuser=True).first()
    
    # Base path for seed images
    seed_images_base = os.path.join(settings.MEDIA_ROOT, 'seed_images', 'store')
    
    for product in products:
        # Get image paths from product (set in create_products)
        image_paths = getattr(product, '_image_paths', [])
        
        if not image_paths:
            if stdout:
                stdout.write(style.WARNING(f'⚠️  No image paths for product: {product.name}'))
            continue
        
        # Delete existing media links for this product to avoid duplicates
        product_content_type = ContentType.objects.get_for_model(Product)
        MediaLink.objects.filter(
            content_type=product_content_type,
            object_id=product.id
        ).delete()
        
        for position, image_path in enumerate(image_paths, start=1):
            # Full path to image file
            full_image_path = os.path.join(seed_images_base, image_path)
            
            # Check if file exists
            if not os.path.exists(full_image_path):
                if stdout:
                    stdout.write(style.WARNING(f'⚠️  Image not found: {full_image_path}, skipping'))
                continue
            
            # Copy file to media directory for workspace
            # Use media_upload_to logic: media/{workspace_id}/products/{filename}
            filename = os.path.basename(image_path)
            workspace_media_dir = os.path.join(settings.MEDIA_ROOT, str(workspace.id), 'products')
            os.makedirs(workspace_media_dir, exist_ok=True)
            
            # Destination file path
            dest_file_path = os.path.join(workspace_media_dir, filename)
            
            # Copy file if it doesn't exist or is different
            if not os.path.exists(dest_file_path) or os.path.getsize(dest_file_path) != os.path.getsize(full_image_path):
                shutil.copy2(full_image_path, dest_file_path)
            
            # Relative path for FileField (relative to MEDIA_ROOT)
            # FileField automatically prepends MEDIA_ROOT, so we use: {workspace_id}/products/{filename}
            relative_path = os.path.join(str(workspace.id), 'products', filename)
            
            # Create Media object with file field
            # Use file path as unique identifier to avoid conflicts
            media_obj, media_created = Media.objects.get_or_create(
                workspace=workspace,
                file=relative_path,
                defaults={
                    'media_type': 'image',
                    'alt_text': f'{product.name} - Image {position}',
                    'uploaded_by': admin_user,
                    'external_url': '',  # Clear external_url to use file field
                }
            )
            
            # Update alt_text and clear external_url if media already existed
            if not media_created:
                if media_obj.alt_text != f'{product.name} - Image {position}':
                    media_obj.alt_text = f'{product.name} - Image {position}'
                # Clear external_url to ensure file field is used
                if media_obj.external_url:
                    media_obj.external_url = ''
                media_obj.save()
            
            # Create MediaLink referencing the Media object
            # unique_together is (content_type, object_id, media), so check if this media is already linked
            try:
                product_media = MediaLink.objects.get(
                    content_type=product_content_type,
                    object_id=product.id,
                    media=media_obj
                )
                # Update position if it changed
                if product_media.position != position:
                    product_media.position = position
                    product_media.description = 'Product image' if position == 1 else ''
                    product_media.save()
                    if stdout:
                        stdout.write(style.SUCCESS(f'↻ Updated product media for: {product.name} (position {position})'))
            except MediaLink.DoesNotExist:
                # Create new MediaLink
                product_media = MediaLink.objects.create(
                    content_type=product_content_type,
                    object_id=product.id,
                    media=media_obj,
                    position=position,
                    description='Product image' if position == 1 else ''
                )
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created product media for: {product.name} (position {position})'))


def create_sales_channels(workspace, stdout=None, style=None):
    """Create sales channels"""
    channels_data = [
        {'name': 'Online Store', 'code': 'online-store', 'channel_type': 'online', 'description': 'Main online store'},
        {'name': 'Mobile App', 'code': 'mobile-app', 'channel_type': 'mobile', 'description': 'Mobile application'},
    ]
    channels = []
    for data in channels_data:
        channel, created = SalesChannel.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            defaults={
                'name': data['name'],
                'channel_type': data['channel_type'],
                'description': data['description'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created sales channel: {channel.name}'))
        channels.append(channel)
    return channels


def create_channel_listings(workspace, products, categories, channels, stdout=None, style=None):
    """Create product and category channel listings"""
    for channel in channels:
        # Add all products to all channels
        for product in products:
            listing, created = ProductChannelListing.objects.get_or_create(
                channel=channel,
                product=product
            )
        
        # Add all categories to all channels
        for category in categories:
            collection, created = ChannelCollection.objects.get_or_create(
                channel=channel,
                category=category
            )
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created channel listings for products and categories'))


def create_returns(workspace, orders, customers, stdout=None, style=None):
    """Create return requests"""
    if not orders:
        return []
    
    returns = []
    for order in orders[:1]:  # Create return for first order
        return_number = f'RET-{timezone.now().strftime("%Y%m%d")}-0001'
        return_request, created = Return.objects.get_or_create(
            workspace=workspace,
            return_number=return_number,
            defaults={
                'order': order,
                'customer': order.customer,
                'status': 'open',
                'reason_category': 'defective',
                'customer_note': 'Product arrived damaged',
            }
        )
        if created:
            # Add return line items
            for item in order.items.all()[:1]:  # Return first item
                return_item = ReturnLineItem.objects.create(
                    return_request=return_request,
                    order_item=item,
                    quantity=1,
                    reason='Defective product',
                    restock_action='damage',
                )
            returns.append(return_request)
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created return: {return_request.return_number}'))
    
    return returns


def create_product_tags(workspace, stdout=None, style=None):
    """Create product tags"""
    tags_data = [
        {'name': 'New Arrival', 'slug': 'new-arrival'},
        {'name': 'Best Seller', 'slug': 'best-seller'},
        {'name': 'Sale', 'slug': 'sale'},
        {'name': 'Featured', 'slug': 'featured'},
    ]
    tags = []
    for tag_data in tags_data:
        tag, created = ProductTag.objects.get_or_create(
            workspace=workspace,
            slug=tag_data['slug'],
            language='en',
            defaults={
                'name': tag_data['name'],
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created product tag: {tag.name}'))
        tags.append(tag)
    return tags


def create_product_variants(workspace, products, stdout=None, style=None):
    """Create product variants with comprehensive options"""
    if not products:
        return []
    
    variants = []
    # More comprehensive variant options for different product types
    variant_configs = [
        # Size-based variants (for clothing, etc.)
        {
            'options': [
                {'sku': 'S', 'name': 'Small', 'price_adjustment': Decimal('-5.00'), 'stock_base': 50},
                {'sku': 'M', 'name': 'Medium', 'price_adjustment': Decimal('0.00'), 'stock_base': 100},
                {'sku': 'L', 'name': 'Large', 'price_adjustment': Decimal('5.00'), 'stock_base': 80},
                {'sku': 'XL', 'name': 'Extra Large', 'price_adjustment': Decimal('10.00'), 'stock_base': 40},
            ]
        },
        # Color-based variants
        {
            'options': [
                {'sku': 'BLACK', 'name': 'Black', 'price_adjustment': Decimal('0.00'), 'stock_base': 75},
                {'sku': 'WHITE', 'name': 'White', 'price_adjustment': Decimal('0.00'), 'stock_base': 60},
                {'sku': 'RED', 'name': 'Red', 'price_adjustment': Decimal('3.00'), 'stock_base': 45},
                {'sku': 'BLUE', 'name': 'Blue', 'price_adjustment': Decimal('3.00'), 'stock_base': 55},
            ]
        },
        # Size + Color combinations
        {
            'options': [
                {'sku': 'S-BLACK', 'name': 'Small Black', 'price_adjustment': Decimal('-2.00'), 'stock_base': 30},
                {'sku': 'M-BLACK', 'name': 'Medium Black', 'price_adjustment': Decimal('0.00'), 'stock_base': 50},
                {'sku': 'L-BLACK', 'name': 'Large Black', 'price_adjustment': Decimal('3.00'), 'stock_base': 40},
                {'sku': 'M-WHITE', 'name': 'Medium White', 'price_adjustment': Decimal('0.00'), 'stock_base': 45},
            ]
        },
    ]
    
    # Create variants for each product with different configurations
    for idx, product in enumerate(products):
        config = variant_configs[idx % len(variant_configs)]
        
        for var_data in config['options']:
            sku = f'{product.slug.upper()}-{var_data["sku"]}'
            variant, created = ProductVariant.objects.get_or_create(
                product=product,
                sku=sku,
                defaults={
                    'name': var_data['name'],
                    'price': product.price + var_data['price_adjustment'],
                    'stock_quantity': var_data['stock_base'],  # Will be synced from VariantInventory
                    'is_active': True,
                    'options': {'size': var_data.get('size'), 'color': var_data.get('color')} if 'size' in var_data.get('sku', '') or 'color' in var_data.get('sku', '').lower() else {},
                }
            )
            if created and stdout:
                stdout.write(style.SUCCESS(f'✓ Created product variant: {variant.sku} (stock: {var_data["stock_base"]})'))
            variants.append(variant)
    
    return variants


def create_product_reviews(workspace, products, customers, stdout=None, style=None):
    """Create product reviews"""
    if not products or not customers:
        return []
    
    reviews = []
    review_data = [
        {'rating': 5, 'title': 'Excellent Product!', 'comment': 'This product exceeded my expectations. Highly recommended!'},
        {'rating': 4, 'title': 'Very Good', 'comment': 'Great quality and fast shipping. Would buy again.'},
        {'rating': 3, 'title': 'Average', 'comment': 'The product is okay, nothing special but does the job.'},
        {'rating': 5, 'title': 'Amazing!', 'comment': 'Best purchase I have ever made. Love it!'},
        {'rating': 4, 'title': 'Good Value', 'comment': 'Good product for the price. Satisfied with my purchase.'},
    ]
    
    for i, product in enumerate(products[:2]):  # Add reviews to first 2 products
        for j, customer in enumerate(customers[:3]):  # Each product gets reviews from 3 customers
            data = review_data[(i + j) % len(review_data)]
            try:
                review, created = ProductReview.objects.get_or_create(
                    workspace=workspace,
                    product=product,
                    customer=customer,
                    defaults={
                        'rating': data['rating'],
                        'title': data['title'],
                        'comment': data['comment'],
                        'is_verified_purchase': True,
                        'is_approved': True,
                    }
                )
                if created:
                    reviews.append(review)
                    if stdout:
                        stdout.write(style.SUCCESS(f'✓ Created review for {product.name} by {customer}'))
            except IntegrityError:
                pass  # Already exists
    
    return reviews


def create_carts(workspace, customer_users, products, variants, stdout=None, style=None):
    """Create shopping carts for customers"""
    from bfg.common.models import Customer
    
    if not customer_users or not products:
        return []
    
    carts = []
    for i, customer_user in enumerate(customer_users[:2]):  # Create carts for first 2 customers
        customer = Customer.objects.filter(workspace=workspace, user=customer_user).first()
        if not customer:
            continue
        
        cart, created = Cart.objects.get_or_create(
            workspace=workspace,
            customer=customer,
            defaults={}
        )
        
        if created:
            # Add items to cart
            for j, product in enumerate(products[:2]):  # Add 2 products to cart
                variant = variants[j] if variants and j < len(variants) else None
                cart_item = CartItem.objects.create(
                    cart=cart,
                    product=product,
                    variant=variant,
                    quantity=j + 1,
                    price=variant.price if variant else product.price,
                )
            carts.append(cart)
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created cart for customer: {customer}'))
    
    return carts


def create_variant_inventory(workspace, variants, stdout=None, style=None):
    """Create variant inventory records with realistic stock distribution"""
    from bfg.delivery.models import Warehouse
    
    if not variants:
        return
    
    warehouses = Warehouse.objects.filter(workspace=workspace)
    if not warehouses.exists():
        if stdout:
            stdout.write(style.WARNING('⚠️  No warehouses found, skipping inventory creation'))
        return
    
    # Create inventory with different quantities per warehouse for realistic distribution
    warehouse_stock_distributions = [
        {'main': 60, 'secondary': 30, 'reserved': 5},  # Main warehouse has more stock
        {'main': 40, 'secondary': 20, 'reserved': 3},  # Different distribution
        {'main': 50, 'secondary': 25, 'reserved': 2},  # Balanced distribution
    ]
    
    for idx, variant in enumerate(variants):
        dist = warehouse_stock_distributions[idx % len(warehouse_stock_distributions)]
        
        for warehouse_idx, warehouse in enumerate(warehouses):
            # Distribute stock: first warehouse gets 'main', others get 'secondary'
            if warehouse_idx == 0:
                quantity = dist['main']
                reserved = dist['reserved']
            else:
                quantity = dist['secondary']
                reserved = max(0, dist['reserved'] - 1)
            
            inventory, created = VariantInventory.objects.get_or_create(
                variant=variant,
                warehouse=warehouse,
                defaults={
                    'quantity': quantity,
                    'reserved': reserved,
                }
            )
            
            # Update if already exists to ensure correct values
            if not created:
                inventory.quantity = quantity
                inventory.reserved = reserved
                inventory.save()
            
            if created and stdout:
                stdout.write(style.SUCCESS(
                    f'✓ Created inventory for {variant.sku} @ {warehouse.name}: '
                    f'{quantity} total, {reserved} reserved, {quantity - reserved} available'
                ))
        
        # Sync variant's stock_quantity from inventory totals
        from django.db.models import Sum
        total_quantity = VariantInventory.objects.filter(
            variant=variant
        ).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        
        variant.stock_quantity = total_quantity
        variant.save()
        
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Synced variant {variant.sku} stock_quantity: {total_quantity}'))


def sync_product_sku_and_stock(workspace, products, variants, stdout=None, style=None):
    """Sync product SKU and stock_quantity from variants"""
    from django.db.models import Sum
    
    for product in products:
        # Set product SKU from first variant or generate from slug
        product_variants = [v for v in variants if v.product == product]
        if product_variants:
            # Use first variant's SKU base (remove variant suffix)
            first_variant_sku = product_variants[0].sku
            # Extract base SKU (before last hyphen)
            if '-' in first_variant_sku:
                base_sku = '-'.join(first_variant_sku.split('-')[:-1])
            else:
                base_sku = first_variant_sku
            product.sku = base_sku
        else:
            # Generate SKU from slug if no variants
            product.sku = product.slug.upper().replace('-', '')
        
        # Calculate product stock_quantity from all variants
        product_total = ProductVariant.objects.filter(
            product=product
        ).aggregate(
            total=Sum('stock_quantity')
        )['total'] or 0
        
        product.stock_quantity = product_total
        product.save()
        
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Synced product {product.name} SKU: {product.sku}, stock: {product_total}'))


def create_product_batches(workspace, products, variants, stdout=None, style=None):
    """Create product batches with comprehensive batch data for inventory tracking"""
    from bfg.delivery.models import Warehouse
    from datetime import timedelta
    from .models import BatchMovement
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    if not variants:
        return []
    
    warehouses = Warehouse.objects.filter(workspace=workspace)
    if not warehouses.exists():
        if stdout:
            stdout.write(style.WARNING('⚠️  No warehouses found, skipping batch creation'))
        return []
    
    batches = []
    base_date = timezone.now().date()
    admin_user = User.objects.filter(is_superuser=True).first()
    
    # Create multiple batches per variant/warehouse combination for realistic inventory tracking
    batch_configs = [
        {
            'quantity': 30,
            'reserved': 3,
            'days_old': 60,
            'days_to_expiry': 300,
            'quality': 'normal'
        },
        {
            'quantity': 25,
            'reserved': 2,
            'days_old': 30,
            'days_to_expiry': 330,
            'quality': 'normal'
        },
        {
            'quantity': 20,
            'reserved': 1,
            'days_old': 10,
            'days_to_expiry': 350,
            'quality': 'normal'
        },
        {
            'quantity': 15,
            'reserved': 0,
            'days_old': 5,
            'days_to_expiry': 360,
            'quality': 'normal'
        },
        # Near expiry batch
        {
            'quantity': 10,
            'reserved': 0,
            'days_old': 330,
            'days_to_expiry': 30,
            'quality': 'warning'
        },
    ]
    
    for variant in variants:
        # Get inventory for this variant to match batch quantities
        variant_inventories = VariantInventory.objects.filter(variant=variant)
        
        for warehouse in warehouses:
            # Get inventory for this variant/warehouse
            inventory = variant_inventories.filter(warehouse=warehouse).first()
            if not inventory:
                continue
            
            # Create multiple batches that sum up to inventory quantity
            total_batch_quantity = 0
            batch_count = 0
            
            for batch_idx, batch_config in enumerate(batch_configs):
                # Only create batches if we haven't exceeded inventory quantity
                if total_batch_quantity >= inventory.quantity:
                    break
                
                batch_quantity = min(
                    batch_config['quantity'],
                    inventory.quantity - total_batch_quantity
                )
                
                if batch_quantity <= 0:
                    continue
                
                batch_number = f'BATCH-{variant.sku}-{warehouse.code}-{batch_idx + 1:03d}'
                
                batch, created = ProductBatch.objects.get_or_create(
                    workspace=workspace,
                    variant=variant,
                    warehouse=warehouse,
                    batch_number=batch_number,
                    defaults={
                        'manufactured_date': base_date - timedelta(days=batch_config['days_old']),
                        'expiry_date': base_date + timedelta(days=batch_config['days_to_expiry']) if batch_config['days_to_expiry'] > 0 else None,
                        'quantity': batch_quantity,
                        'reserved': batch_config['reserved'],
                        'purchase_price': variant.price * Decimal('0.6'),  # 60% of sale price
                        'quality_status': batch_config['quality'],
                    }
                )
                
                if created:
                    batches.append(batch)
                    total_batch_quantity += batch_quantity
                    batch_count += 1
                    
                    if stdout:
                        available = batch.quantity - batch.reserved
                        stdout.write(style.SUCCESS(
                            f'✓ Created batch: {batch.batch_number} - '
                            f'Qty: {batch.quantity}, Reserved: {batch.reserved}, '
                            f'Available: {available}, Status: {batch.quality_status}'
                        ))
                    
                    # Create batch movement for initial stock
                    BatchMovement.objects.create(
                        batch=batch,
                        movement_type='in',
                        quantity=batch_quantity,
                        reason='Initial stock receipt',
                        performed_by=admin_user,
                    )
                    
                    # Create some additional movements for realistic history
                    if batch_idx > 0:  # Add some out movements for older batches
                        BatchMovement.objects.create(
                            batch=batch,
                            movement_type='out',
                            quantity=-5,  # Negative for out
                            reason='Order fulfillment',
                            performed_by=admin_user,
                        )
            
            if stdout and batch_count > 0:
                stdout.write(style.SUCCESS(
                    f'✓ Created {batch_count} batches for {variant.sku} @ {warehouse.name} '
                    f'(Total: {total_batch_quantity} units)'
                ))
    
    return batches


def create_subscription_plans(workspace, stdout=None, style=None):
    """Create subscription plans"""
    plans_data = [
        {
            'name': 'Basic Plan',
            'description': 'Perfect for individuals getting started',
            'price': Decimal('9.99'),
            'interval': 'month',
            'interval_count': 1,
            'trial_period_days': 7,
            'features': ['Basic features', 'Email support', '5 products']
        },
        {
            'name': 'Pro Plan',
            'description': 'Best for growing businesses',
            'price': Decimal('29.99'),
            'interval': 'month',
            'interval_count': 1,
            'trial_period_days': 14,
            'features': ['All basic features', 'Priority support', 'Unlimited products', 'Advanced analytics']
        },
        {
            'name': 'Enterprise Plan',
            'description': 'For large organizations with custom needs',
            'price': Decimal('99.99'),
            'interval': 'month',
            'interval_count': 1,
            'trial_period_days': 30,
            'features': ['All pro features', '24/7 support', 'Custom integrations', 'Dedicated account manager']
        },
        {
            'name': 'Annual Basic',
            'description': 'Basic plan with annual billing (save 20%)',
            'price': Decimal('95.90'),
            'interval': 'year',
            'interval_count': 1,
            'trial_period_days': 7,
            'features': ['Basic features', 'Email support', '5 products']
        },
        {
            'name': 'Weekly Plan',
            'description': 'Short-term subscription option',
            'price': Decimal('2.99'),
            'interval': 'week',
            'interval_count': 1,
            'trial_period_days': 3,
            'features': ['Basic features', 'Email support']
        }
    ]
    
    plans = []
    for plan_data in plans_data:
        plan, created = SubscriptionPlan.objects.get_or_create(
            workspace=workspace,
            name=plan_data['name'],
            defaults={
                'description': plan_data['description'],
                'price': plan_data['price'],
                'interval': plan_data['interval'],
                'interval_count': plan_data['interval_count'],
                'trial_period_days': plan_data['trial_period_days'],
                'features': plan_data['features'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created subscription plan: {plan.name}'))
        plans.append(plan)
    
    return plans


def create_order_notification_templates(workspace, stdout=None, style=None):
    """Create order notification message templates"""
    from bfg.inbox.models import MessageTemplate
    
    if stdout:
        stdout.write(style.SUCCESS('Creating order notification templates...'))
    
    templates_data = [
        {
            'name': 'Order Created',
            'code': 'order_created',
            'event': 'order.created',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Order Confirmation - {{ order.order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

Thank you for your order!

Order Number: {{ order.order_number }}
Order Date: {{ order.created_at }}
Total Amount: ${{ order.total }}

We will send you another email when your order ships.

Thank you for shopping with us!''',
            'app_message_enabled': True,
            'app_message_title': 'Order Created',
            'app_message_body': 'Your order {{ order.order_number }} has been created. Total: ${{ order.total }}',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Order Confirmed',
            'push_body': 'Order {{ order.order_number }} confirmed. Total: ${{ order.total }}',
        },
        {
            'name': 'Order Processing',
            'code': 'order_processing',
            'event': 'order.processing',
            'language': 'en',
            'email_enabled': False,  # Optional notification
            'email_subject': 'Your order is being processed',
            'email_body': 'Your order {{ order.order_number }} is being processed.',
            'app_message_enabled': True,
            'app_message_title': 'Order Processing',
            'app_message_body': 'Your order {{ order.order_number }} is being processed.',
            'sms_enabled': False,
            'push_enabled': False,
        },
        {
            'name': 'Order Shipped',
            'code': 'order_shipped',
            'event': 'order.shipped',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Your order has been shipped - {{ order.order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

Great news! Your order has been shipped.

Order Number: {{ order.order_number }}
Tracking Number: {{ tracking_number }}
{% if tracking_url %}
Track your order: {{ tracking_url }}
{% endif %}

Your order is on its way!''',
            'app_message_enabled': True,
            'app_message_title': 'Order Shipped',
            'app_message_body': 'Your order {{ order.order_number }} has been shipped. Tracking: {{ tracking_number }}',
            'sms_enabled': True,
            'sms_body': 'Order {{ order.order_number }} shipped! Track: {{ tracking_number }}',
            'push_enabled': True,
            'push_title': 'Order Shipped',
            'push_body': 'Order {{ order.order_number }} shipped. Track: {{ tracking_number }}',
        },
        {
            'name': 'Order Delivered',
            'code': 'order_delivered',
            'event': 'order.delivered',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Your order has been delivered - {{ order.order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

Your order has been delivered!

Order Number: {{ order.order_number }}
Delivered At: {{ order.delivered_at }}

We hope you love your purchase! Please leave a review if you have a moment.

Thank you for shopping with us!''',
            'app_message_enabled': True,
            'app_message_title': 'Order Delivered',
            'app_message_body': 'Your order {{ order.order_number }} has been delivered!',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Order Delivered',
            'push_body': 'Order {{ order.order_number }} has been delivered!',
        },
        {
            'name': 'Order Cancelled',
            'code': 'order_cancelled',
            'event': 'order.cancelled',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Order Cancelled - {{ order.order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

Your order has been cancelled.

Order Number: {{ order.order_number }}
{% if cancellation_reason %}
Reason: {{ cancellation_reason }}
{% endif %}

If you have any questions, please contact our support team.

Thank you.''',
            'app_message_enabled': True,
            'app_message_title': 'Order Cancelled',
            'app_message_body': 'Your order {{ order.order_number }} has been cancelled.{% if cancellation_reason %} Reason: {{ cancellation_reason }}{% endif %}',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Order Cancelled',
            'push_body': 'Order {{ order.order_number }} has been cancelled.',
        },
        {
            'name': 'Order Refunded',
            'code': 'order_refunded',
            'event': 'order.refunded',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Refund Processed - {{ order.order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

Your refund has been processed.

Order Number: {{ order.order_number }}
Refund Amount: ${{ refund_amount }}

The refund will be credited to your original payment method within 5-10 business days.

Thank you.''',
            'app_message_enabled': True,
            'app_message_title': 'Refund Processed',
            'app_message_body': 'Refund of ${{ refund_amount }} processed for order {{ order.order_number }}.',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Refund Processed',
            'push_body': 'Refund of ${{ refund_amount }} for order {{ order.order_number }}.',
        },
        {
            'name': 'Payment Received',
            'code': 'payment_received',
            'event': 'payment.completed',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Payment Received - {{ order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

We have received your payment.

Order Number: {{ order_number }}
Amount: {{ currency }} {{ amount }}

Thank you for your payment!''',
            'app_message_enabled': True,
            'app_message_title': 'Payment Received',
            'app_message_body': 'Payment of {{ currency }} {{ amount }} received for order {{ order_number }}.',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Payment Received',
            'push_body': 'Payment of {{ currency }} {{ amount }} received.',
        },
        {
            'name': 'Payment Failed',
            'code': 'payment_failed',
            'event': 'payment.failed',
            'language': 'en',
            'email_enabled': True,
            'email_subject': 'Payment Failed - {{ order_number }}',
            'email_body': '''Dear {{ customer.full_name }},

Unfortunately, your payment could not be processed.

Order Number: {{ order_number }}
Amount: {{ currency }} {{ amount }}
{% if failure_reason %}
Reason: {{ failure_reason }}
{% endif %}

Please check your payment method and try again, or contact our support team for assistance.

Thank you.''',
            'app_message_enabled': True,
            'app_message_title': 'Payment Failed',
            'app_message_body': 'Payment for order {{ order_number }} failed.{% if failure_reason %} Reason: {{ failure_reason }}{% endif %}',
            'sms_enabled': False,
            'push_enabled': True,
            'push_title': 'Payment Failed',
            'push_body': 'Payment for order {{ order_number }} failed. Please try again.',
        },
    ]
    
    templates = []
    created_count = 0
    updated_count = 0
    
    for data in templates_data:
        try:
            # Use update_or_create to update existing templates with complete data
            template, created = MessageTemplate.objects.update_or_create(
                workspace=workspace,
                code=data['code'],
                language=data['language'],
                defaults={
                    'name': data['name'],
                    'event': data['event'],
                    'email_enabled': data.get('email_enabled', False),
                    'email_subject': data.get('email_subject', ''),
                    'email_body': data.get('email_body', ''),
                    'app_message_enabled': data.get('app_message_enabled', False),
                    'app_message_title': data.get('app_message_title', ''),
                    'app_message_body': data.get('app_message_body', ''),
                    'sms_enabled': data.get('sms_enabled', False),
                    'sms_body': data.get('sms_body', ''),
                    'push_enabled': data.get('push_enabled', False),
                    'push_title': data.get('push_title', ''),
                    'push_body': data.get('push_body', ''),
                    'is_active': True,
                    'available_variables': {
                        'order': ['order_number', 'total', 'subtotal', 'status', 'created_at', 'shipped_at', 'delivered_at'],
                        'customer': ['full_name', 'email', 'phone'],
                        'tracking_number': 'string',
                        'tracking_url': 'string',
                        'cancellation_reason': 'string',
                        'refund_amount': 'string',
                        'amount': 'string',
                        'currency': 'string',
                        'order_number': 'string',
                        'failure_reason': 'string',
                    }
                }
            )
            if created:
                created_count += 1
                if stdout:
                    stdout.write(style.SUCCESS(f'✓ Created message template: {template.name} ({template.code})'))
            else:
                updated_count += 1
                if stdout:
                    stdout.write(style.SUCCESS(f'↻ Updated message template: {template.name} ({template.code})'))
            templates.append(template)
        except Exception as e:
            if stdout:
                stdout.write(style.ERROR(f'✗ Failed to create template {data.get("code", "unknown")}: {str(e)}'))
            import traceback
            if stdout:
                stdout.write(style.ERROR(traceback.format_exc()))
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {created_count} templates, updated {updated_count} templates (total: {len(templates)})'))
    
    return templates

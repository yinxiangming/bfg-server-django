# BFG2_SHOP Module - E-commerce

## Overview

The `bfg2_shop` module provides complete e-commerce functionality including product catalog, shopping cart, order management, and inventory control.

## Features

- 🛍️ **Product Catalog** - Multi-category products with hierarchical organization
- 🏷️ **Flexible Tagging** - ManyToMany product tagging
- 📦 **Subscription/Plans** - Recurring subscription products (monthly, yearly)
- 🎨 **Product Variants** - Size, color, material combinations
- 📊 **Inventory Control** - Per-warehouse stock tracking for each variant
- 🛒 **Shopping Cart** - Session-based cart with saved carts
- 📝 **Order Management** - Complete order lifecycle with customizable statuses
- ⭐ **Reviews & Ratings** - Customer product reviews
- 💰 **Flexible Pricing** - Regular, sale, tiered pricing for subscriptions

## Models

### ProductCategory

**Purpose**: Hierarchical product categorization.

```python
class ProductCategory(models.Model):
    """
    Product category with hierarchy and multi-language support.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    
    # Hierarchy
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    level = models.IntegerField(default=0)  # Auto-calculated depth
    path = models.CharField(max_length=255)  # e.g., "/electronics/phones/"
    
    # Display
    image = models.ImageField(upload_to='categories/', blank=True)
    icon = models.CharField(max_length=50, blank=True)
    banner = models.ImageField(upload_to='category_banners/', blank=True)
    
    # SEO
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    
    # Settings
    order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    
    # Language
    language = models.CharField(max_length=10)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `workspace + slug + language`, `workspace + parent`, `path`

---

### ProductTag

**Purpose**: Flexible product tagging (ManyToMany).

```python
class ProductTag(models.Model):
    """
    Product tag for flexible categorization.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50)
    
    # Display
    color = models.CharField(max_length=20, blank=True)
    icon = models.CharField(max_length=50, blank=True)
    
    # Language
    language = models.CharField(max_length=10)
    
    order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('workspace', 'slug', 'language')
        ordering = ['order', 'name']
```

---

### Product

**Purpose**: Base product information (master product).

```python
class Product(models.Model):
    """
    Master product. Variants provide specific SKUs.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    sku = models.CharField(max_length=100)  # Master SKU
    
    # Content
    description = models.TextField()
    short_description = models.TextField(blank=True)
    
    # Categorization (ManyToMany - product can belong to multiple categories)
    categories = models.ManyToManyField(ProductCategory)
    primary_category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name='primary_products', null=True, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    tags = models.ManyToManyField('ProductTag', blank=True)  # ManyToMany relationship
    
    # Pricing (base price, variants can override)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='NZD')
    
    # Physical properties
    weight = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # kg
    length = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # cm
    width = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    height = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Inventory
    track_inventory = models.BooleanField(default=True)
    stock_quantity = models.IntegerField(default=0)
    low_stock_threshold = models.IntegerField(default=10)
    
    # Customs (for international shipping)
    hs_code = models.CharField(max_length=50, blank=True)
    country_of_origin = models.CharField(max_length=2, blank=True)
    
    # SEO
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)
    
    # Settings
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_featured = models.BooleanField(default=False)
    is_virtual = models.BooleanField(default=False)  # Digital products
    requires_shipping = models.BooleanField(default=True)
    is_subscription = models.BooleanField(default=False)  # Recurring product/plan
    
    # Sales tracking
    view_count = models.IntegerField(default=0)
    sales_count = models.IntegerField(default=0)
    
    # Language
    language = models.CharField(max_length=10)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `workspace + slug + language`, `workspace + sku`, `status`

---

### SubscriptionPlan

**Purpose**: Recurring subscription configuration for products.

```python
class SubscriptionPlan(models.Model):
    """
    Subscription/recurring payment plan for products.
    """
    INTERVAL_CHOICES = (
        ('day', 'Daily'),
        ('week', 'Weekly'),
        ('month', 'Monthly'),
        ('year', 'Yearly'),
    )
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='subscription_plans')
    
    # Plan details
    name = models.CharField(max_length=100)  # e.g., "Monthly Plan", "Annual Plan"
    
    # Billing
    interval = models.CharField(max_length=20, choices=INTERVAL_CHOICES, default='month')
    interval_count = models.IntegerField(default=1)  # e.g., every 3 months
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    setup_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Trial
    trial_period_days = models.IntegerField(default=0)
    
    # Settings
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=100)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Subscription

**Purpose**: Active customer subscription.

```python
class Subscription(models.Model):
    """
    Active customer subscription.
    """
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('past_due', 'Past Due'),
        ('trialing', 'Trial Period'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    
    # Plan
    product = models.Foreign Key(Product, on_delete=models.PROTECT)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Dates
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    trial_end = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Payment tracking
    last_payment_at = models.DateTimeField(null=True, blank=True)
    next_payment_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### VariantInventory

**Purpose**: Stock levels per variant per warehouse.

```python
class VariantInventory(models.Model):
    """
    Inventory tracking for product variants in different warehouses.
    """
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='inventory')
    warehouse = models.ForeignKey('bfg.delivery.Warehouse', on_delete=models.CASCADE)
    
    # Stock levels
    quantity_on_hand = models.IntegerField(default=0)
    quantity_reserved = models.IntegerField(default=0)  # Reserved for pending orders
    quantity_available = models.IntegerField(default=0)  # Calculated: on_hand - reserved
    
    # Reorder
    reorder_point = models.IntegerField(default=10)
    reorder_quantity = models.IntegerField(default=50)
    
    # Tracking
    last_stock_count = models.DateTimeField(null=True, blank=True)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('variant', 'warehouse')
        verbose_name_plural = 'Variant Inventories'
```

---

### ProductVariant

**Purpose**: Product variations (size, color, etc.).

```python
class ProductVariant(models.Model):
    """
    Product variant with specific attributes and SKU.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    
    # Identification
    sku = models.CharField(max_length=100, unique=True)
    barcode = models.CharField(max_length=100, blank=True)
    
    # Variant attributes (e.g., "Size: L, Color: Red")
    attributes = models.JSONField(default=dict)  # {"size": "L", "color": "Red"}
    
    # Pricing (can override product price)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Inventory
    stock_quantity = models.IntegerField(default=0)
    
    # Physical (can override product dimensions)
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    
    # Display
    image = models.ImageField(upload_to='variants/', blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
```

**Indexes**: `product`, `sku`

---

### ProductImage

**Purpose**: Product gallery images.

```python
class ProductImage(models.Model):
    """
    Product image gallery.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE)
    
    image = models.ImageField(upload_to='products/%Y/%m/')
    alt_text = models.CharField(max_length=255, blank=True)
    
    is_primary = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### Cart

**Purpose**: Shopping cart for a customer.

```python
class Cart(models.Model):
    """
    Shopping cart.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', null=True, blank=True, on_delete=models.CASCADE)
    
    session_key = models.CharField(max_length=100, blank=True)  # For guests
    
    # Totals (calculated)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Applied promotions
    coupon = models.ForeignKey('bfg2_promo.Coupon', null=True, blank=True, on_delete=models.SET_NULL)
    
    # Saved cart
    is_saved = models.BooleanField(default=False)
    saved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### CartItem

**Purpose**: Items in a shopping cart.

```python
class CartItem(models.Model):
    """
    Cart line item.
    """
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    
    # Product reference
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE)
    
    # Snapshot prices (at time of adding)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### OrderStatus

**Purpose**: Customizable order statuses per workspace.

```python
class OrderStatus(models.Model):
    """
    Order status configuration (customizable per workspace).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default='#000000')  # Hex color
    
    # System events (optional mapping)
    event = models.CharField(max_length=30, blank=True)  # 'created', 'paid', 'shipped', etc.
    
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### Order

**Purpose**: Customer order.

```python
class Order(models.Model):
    """
    Customer order.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    
    # Order identification
    order_number = models.CharField(max_length=100, unique=True)
    
    # Addresses
    billing_address = models.ForeignKey('common.Address', related_name='billing_orders', on_delete=models.PROTECT)
    shipping_address = models.ForeignKey('common.Address', related_name='shipping_orders', on_delete=models.PROTECT)
    
    # Financial
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='NZD')
    
    # Payment
    payment_method = models.CharField(max_length=50)
    payment_status = models.CharField(max_length=20, default='pending')
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Status
    status = models.ForeignKey(OrderStatus, on_delete=models.PROTECT)
    
    # Fulfillment
    consignment = models.ForeignKey('bfg2_delivery.Consignment', null=True, blank=True, on_delete=models.SET_NULL)
    
    # Promotions
    coupon = models.ForeignKey('bfg2_promo.Coupon', null=True, blank=True, on_delete=models.SET_NULL)
    
    # Notes
    customer_note = models.TextField(blank=True)
    internal_note = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `order_number`, `workspace + customer`, `status`, `payment_status`

---

### OrderItem

**Purpose**: Order line items.

```python
class OrderItem(models.Model):
    """
    Order line item with price snapshot.
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    
    # Product reference (snapshot)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.PROTECT)
    
    # Snapshot data (preserve at time of order)
    product_name = models.CharField(max_length=255)
    product_sku = models.CharField(max_length=100)
    variant_attributes = models.JSONField(null=True, blank=True)
    
    # Pricing
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
```

---

### ProductReview

**Purpose**: Customer product reviews.

```python
class ProductReview(models.Model):
    """
    Product review by customer.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL)
    
    # Review
    rating = models.IntegerField()  # 1-5
    title = models.CharField(max_length=255, blank=True)
    content = models.TextField()
    
    # Images
    images = models.JSONField(default=list, blank=True)  # List of image URLs
    
    # Moderation
    is_verified_purchase = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    
    # Engagement
    helpful_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## API Endpoints

### Products
- `GET /api/shop/products/` - List products with filters
- `GET /api/shop/products/{slug}/` - Get product detail
- `GET /api/shop/products/{id}/variants/` - Get product variants
- `GET /api/shop/products/{id}/reviews/` - Get product reviews
- `POST /api/shop/products/` - Create product (admin)

### Cart
- `GET /api/shop/cart/` - Get current cart
- `POST /api/shop/cart/add/` - Add item to cart
- `PUT /api/shop/cart/items/{id}/` - Update cart item
- `DELETE /api/shop/cart/items/{id}/` - Remove cart item
- `POST /api/shop/cart/apply-coupon/` - Apply coupon

### Orders
- `GET /api/shop/orders/` - List customer orders
- `GET /api/shop/orders/{order_number}/` - Get order detail
- `POST /api/shop/orders/checkout/` - Create order from cart
- `POST /api/shop/orders/{id}/cancel/` - Cancel order

### Reviews
- `POST /api/shop/products/{id}/reviews/` - Submit review
- `PUT /api/shop/reviews/{id}/helpful/` - Mark review helpful

## Integration with Other Modules

- **bfg2_finance**: Order payment and invoicing
- **bfg2_delivery**: Order fulfillment and shipping
- **bfg2_promo**: Coupons and discounts applied to orders

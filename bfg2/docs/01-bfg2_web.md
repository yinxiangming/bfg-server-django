# BFG2_WEB Module - Website & CMS

## Overview

The `bfg2_web` module provides comprehensive website building and content management capabilities with multi-language support.

## Features

- 🌐 **Multi-site Support** - Multiple websites per domain
- 🎨 **Theme System** - Customizable templates and themes
- 🔐 **Authentication** - django-allauth integration (social login)
- 📝 **Content Management** - Pages, posts, articles with versioning
- 💬 **Message Center** - User notifications and messaging
- 📱 **SMS Integration** - Send and track SMS messages
- 🌍 **Multi-language Support** - Full i18n with content translation
- 📱 **Responsive Design** - Mobile-first approach
- 🔍 **SEO Optimization** - Meta tags, sitemaps, structured data
- 📰 **Publishing System** - Scheduled publishing, draft/published states
- 🖼️ **Media Library** - Image and file management

## Models

### Site

**Purpose**: Multi-site configuration for serving different websites based on domain.

```python
class Site(models.Model):
    """
    Site configuration for multi-site support.
    Each site can have its own domain, theme, and content.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Identification
    name = models.CharField(max_length=100)
    domain = models.CharField(max_length=255, unique=True)  # e.g., "example.com"
    
    # Theme
    theme = models.ForeignKey('Theme', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Configuration
    default_language = models.CharField(max_length=10, default='en')
    languages = models.JSONField(default=list)  # Enabled languages ['en', 'zh-hans']
    
    # SEO
    site_title = models.CharField(max_length=255)
    site_description = models.TextField(blank=True)
    
    # Settings
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `domain`, `workspace`

---

### Theme

**Purpose**: Theme templates for customizing site appearance.

```python
class Theme(models.Model):
    """
    Theme template with customization options.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)  # Internal code
    description = models.TextField(blank=True)
    
    # Template
    template_path = models.CharField(max_length=255)  # Path to template directory
    
    # Customization
    logo = models.ImageField(upload_to='themes/logos/', blank=True)
    favicon = models.ImageField(upload_to='themes/favicons/', blank=True)
    
    # Colors
    primary_color = models.CharField(max_length=20, default='#007bff')
    secondary_color = models.CharField(max_length=20, default='#6c757d')
    
    # Homepage customization
    homepage_title = models.CharField(max_length=255, blank=True)
    homepage_subtitle = models.CharField(max_length=255, blank=True)
    homepage_text = models.TextField(blank=True)
    homepage_image = models.ImageField(upload_to='themes/homepage/', blank=True)
    
    # Custom CSS/JS
    custom_css = models.TextField(blank=True)
    custom_js = models.TextField(blank=True)
    
    # Settings
    config = models.JSONField(default=dict, blank=True)  # Additional theme settings
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Page

**Purpose**: Manages static and dynamic content pages.

```python
class Page(models.Model):
    """
    Content page with multi-language support and versioning.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    
    # Content
    content = models.TextField()  # Rich text content
    excerpt = models.TextField(blank=True)  # Short summary
    
    # Organization
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    template = models.CharField(max_length=100, default='default')
    
    # SEO
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)
    
    # Publishing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Settings
    is_featured = models.BooleanField(default=False)
    allow_comments = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    
    # Language
    language = models.CharField(max_length=10)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, related_name='pages_created')
```

**Indexes**: `workspace + slug`, `workspace + status`, `workspace + language`

---

### Post

**Purpose**: Blog posts and news articles with categorization and tagging.

```python
class Post(models.Model):
    """
    Blog post or news article.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Basic Info
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    
    # Content
    content = models.TextField()
    excerpt = models.TextField(blank=True)
    featured_image = models.ImageField(upload_to='posts/', blank=True)
    
    # Organization
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True)
    tags = models.ManyToManyField('Tag', blank=True)
    
    # SEO
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    
    # Publishing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Engagement
    view_count = models.IntegerField(default=0)
    comment_count = models.IntegerField(default=0)
    allow_comments = models.BooleanField(default=True)
    
    # Language
    language = models.CharField(max_length=10)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    author = models.ForeignKey(User, on_delete=models.PROTECT)
```

**Indexes**: `workspace + slug + language`, `workspace + status`, `workspace + category`, `published_at`

---

### Category

**Purpose**: Hierarchical categorization for posts and content.

```python
class Category(models.Model):
    """
    Content category with hierarchy support.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    
    # Display
    icon = models.CharField(max_length=50, blank=True)  # Icon class or emoji
    color = models.CharField(max_length=7, blank=True)  # Hex color
    image = models.ImageField(upload_to='categories/', blank=True)
    
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    # Language
    language = models.CharField(max_length=10)
```

**Indexes**: `workspace + slug + language`, `workspace + parent`

---

### Tag

**Purpose**: Flexible tagging system for content.

```python
class Tag(models.Model):
    """
    Content tag for flexible organization.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50)
    
    language = models.CharField(max_length=10)
    
    class Meta:
        unique_together = ('workspace', 'slug', 'language')
```

---

### Menu

**Purpose**: Navigation menu management.

```python
class Menu(models.Model):
    """
    Navigation menu.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    location = models.CharField(max_length=50)  # 'header', 'footer', 'sidebar'
    
    language = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)
```

---

### MenuItem

**Purpose**: Individual menu items with hierarchy.

```python
class MenuItem(models.Model):
    """
    Individual menu item.
    """
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='items')
    
    title = models.CharField(max_length=100)
    url = models.CharField(max_length=255)  # Can be path or full URL
    
    # Links
    page = models.ForeignKey(Page, null=True, blank=True, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    
    # Display
    icon = models.CharField(max_length=50, blank=True)
    css_class = models.CharField(max_length=50, blank=True)
    order = models.IntegerField(default=0)
    
    # Behavior
    open_in_new_tab = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
```

---

### Translation

**Purpose**: Content translations for multi-language support.

```python
class Translation(models.Model):
    """
    Generic translation storage for any translatable content.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Generic relation to any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Translation
    field_name = models.CharField(max_length=50)
    language = models.CharField(max_length=10)
    value = models.TextField()
    
    class Meta:
        unique_together = ('content_type', 'object_id', 'field_name', 'language')
```

---

### Language

**Purpose**: Supported language configuration.

```python
class Language(models.Model):
    """
    Supported language configuration.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=10)  # 'en', 'zh-hans', 'zh-hant'
    name = models.CharField(max_length=100)  # 'English', '简体中文'
    native_name = models.CharField(max_length=100)  # 'English', '简体中文'
    
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    
    # RTL support
    is_rtl = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('workspace', 'code')
```

---

### Media

**Purpose**: Media file management.

```python
class Media(models.Model):
    """
    Media file (image, document, etc.).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # File
    file = models.FileField(upload_to='media/%Y/%m/')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)  # 'image', 'document', 'video'
    mime_type = models.CharField(max_length=100)
    file_size = models.BigIntegerField()  # In bytes
    
    # Metadata
    title = models.CharField(max_length=255, blank=True)
    alt_text = models.CharField(max_length=255, blank=True)
    caption = models.TextField(blank=True)
    
    # Image-specific
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
```

---

### Message

**Purpose**: User messages and notifications.

```python
class Message(models.Model):
    """
    Message/notification sent to users.
    """
    MESSAGE_TYPE_CHOICES = (
        ('notification', 'Notification'),
        ('message', 'Direct Message'),
        ('system', 'System Message'),
        ('announcement', 'Announcement'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Content
    subject = models.CharField(max_length=255)
    message = models.TextField()
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='notification')
    
    # Sender
    sender = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Link/Action
    action_url = models.URLField(blank=True)  # Optional link
    action_label = models.CharField(max_length=100, blank=True)
    
    # Related objects
    related_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey('related_content_type', 'related_object_id')
    
    # Delivery
    send_email = models.BooleanField(default=False)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=False)
    
    # Scheduling
    send_email_at = models.DateTimeField(null=True, blank=True)  # Schedule for later
    send_sms_at = models.DateTimeField(null=True, blank=True)  # Schedule for later
    send_push_at = models.DateTimeField(null=True, blank=True)  # Schedule for later
    
    # Timestamps
    expires_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### MessageTemplate

**Purpose**: System message templates for automated notifications.

```python
class MessageTemplate(models.Model):
    """
    Message template for system events.
    Supports email, app message, and SMS templates.
    """
    EVENT_CHOICES = (
        ('order_created', 'Order Created'),
        ('order_shipped', 'Order Shipped'),
        ('order_delivered', 'Order Delivered'),
        ('payment_received', 'Payment Received'),
        ('subscription_started', 'Subscription Started'),
        ('subscription_ending', 'Subscription Ending Soon'),
        ('welcome', 'Welcome Message'),
        ('password_reset', 'Password Reset'),
        ('ticket_created', 'Support Ticket Created'),
        ('ticket_replied', 'Support Ticket Replied'),
        ('custom', 'Custom Event'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, null=True, blank=True, default=None)
    
    # Template identification
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)  # Internal code
    event = models.CharField(max_length=50, choices=EVENT_CHOICES)
    
    # Email template
    email_enabled = models.BooleanField(default=False)
    email_subject = models.CharField(max_length=255, blank=True)
    email_body = models.TextField(blank=True)  # Supports template variables
    email_html_body = models.TextField(blank=True)  # HTML version
    
    # App message template
    app_message_enabled = models.BooleanField(default=False)
    app_message_title = models.CharField(max_length=255, blank=True)
    app_message_body = models.TextField(blank=True)
    
    # SMS template
    sms_enabled = models.BooleanField(default=False)
    sms_body = models.TextField(max_length=160, blank=True)  # SMS character limit
    
    # Push notification template
    push_enabled = models.BooleanField(default=False)
    push_title = models.CharField(max_length=100, blank=True)
    push_body = models.CharField(max_length=255, blank=True)
    
    # Template variables guide
    available_variables = models.JSONField(default=dict, blank=True)
    # Example: {"order_number": "Order number", "customer_name": "Customer name"}
    
    # Language
    language = models.CharField(max_length=10)
    
    # Settings
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('workspace', 'code', 'language')
        verbose_name = 'Message Template'
```

**Template Variables**: Templates support variable substitution using Django template syntax:
- `{{ customer_name }}` - Customer's name
- `{{ order_number }}` - Order tracking number
- `{{ product_name }}` - Product name
- `{{ amount }}` - Payment amount
- `{{ link }}` - Action link
- Custom variables based on event type

**Usage Example**:
```python
# Get template for order created event
template = MessageTemplate.objects.get(
    workspace=current_workspace,
    event='order_created',
    language='en',
    is_active=True
)

# Generate message from template
context = {
    'customer_name': order.customer.name,
    'order_number': order.order_number,
    'total': order.total,
    'link': f'https://example.com/orders/{order.order_number}'
}

# Render email
from django.template import Template, Context
email_subject = Template(template.email_subject).render(Context(context))
email_body = Template(template.email_body).render(Context(context))

# Create and send message
message = Message.objects.create(
    workspace=current_workspace,
    subject=email_subject,
    message=email_body,
    message_type='system',
    send_email=template.email_enabled,
    send_sms=template.sms_enabled,
    send_push=template.push_enabled
)
```

---

### MessageRecipient

**Purpose**: Message delivery and read tracking per user.

```python
class MessageRecipient(models.Model):
    """
    Message recipient with read status tracking.
    """
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='recipients')
    recipient = models.ForeignKey('common.Customer', on_delete=models.CASCADE)
    
    # Status
    is_read = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    
    # Timestamps
    delivered_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('message', 'recipient')
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'delivered_at']),
        ]
```

---

### SMSMessage

**Purpose**: SMS message tracking and history.

```python
class SMSMessage(models.Model):
    """
    SMS message sent to customers.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE)
    
    # Phone
    phone_number = models.CharField(max_length=20)
    
    # Content
    message = models.TextField(max_length=160)  # SMS character limit
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Provider response
    provider = models.CharField(max_length=50, blank=True)  # Twilio, Plivo, etc.
    provider_id = models.CharField(max_length=100, blank=True)  # External message ID
    provider_response = models.JSONField(default=dict, blank=True)
    
    # Related message
    message_ref = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
```

---

## API Endpoints

### Pages
- `GET /api/web/pages/` - List pages
- `GET /api/web/pages/{slug}/` - Get page by slug
- `POST /api/web/pages/` - Create page (admin)
- `PUT /api/web/pages/{id}/` - Update page (admin)
- `DELETE /api/web/pages/{id}/` - Delete page (admin)

### Posts
- `GET /api/web/posts/` - List posts with filters
- `GET /api/web/posts/{slug}/` - Get post by slug
- `GET /api/web/posts/{id}/related/` - Get related posts
- `POST /api/web/posts/` - Create post (admin)

### Categories & Tags
- `GET /api/web/categories/` - List categories
- `GET /api/web/tags/` - List tags
- `GET /api/web/categories/{slug}/posts/` - Posts in category

### Menus
- `GET /api/web/menus/{location}/` - Get menu by location
- `GET /api/web/languages/` - Get available languages

## Usage Example

```python
# Get homepage in user's language
page = Page.objects.get(
    workspace=current_workspace,
    slug='home',
    language=user_language,
    status='published'
)

# List recent blog posts
posts = Post.objects.filter(
    workspace=current_workspace,
    status='published',
    language='en'
).order_by('-published_at')[:10]

# Get translated content
translation = Translation.objects.get(
    content_type=ContentType.objects.get_for_model(Page),
    object_id=page.id,
    field_name='title',
    language='zh-hans'
)
```

## Multi-language Implementation

BFG2_WEB supports two translation approaches:

1. **Model Translation**: Separate instances per language
2. **Field Translation**: Translation table for specific fields

Both approaches are supported to provide flexibility.

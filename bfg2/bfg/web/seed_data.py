# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.web module.
"""

from django.utils import timezone
from django.core.cache import cache
from .models import Site, Theme, Language, Page, Media, Category, Tag, Menu, MenuItem, Post
from .services.page_service import get_page_rendered_cache_key, HOME_SLUG


def clear_data():
    """Clear web module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect page cache keys before deleting Page (same key format as page_service)
    page_cache_keys = []
    try:
        for row in Page.objects.values_list("workspace_id", "slug", "language").distinct():
            page_cache_keys.append(get_page_rendered_cache_key(row[0], row[1], row[2]))
    except Exception:
        pass

    # 2. Delete in dependency order
    Media.objects.all().delete()
    Post.objects.all().delete()
    MenuItem.objects.all().delete()
    Menu.objects.all().delete()
    Page.objects.all().delete()
    Category.objects.all().delete()
    Tag.objects.all().delete()
    Site.objects.all().delete()
    Theme.objects.all().delete()
    Language.objects.all().delete()

    # 3. Invalidate caches so cleared pages do not serve stale content
    for key in page_cache_keys:
        cache.delete(key)
    try:
        from bfg.common.models import Workspace
        for ws in Workspace.objects.only("id").all():
            for lang in ("en", "zh", "zh-hans"):
                cache.delete(get_page_rendered_cache_key(ws.id, HOME_SLUG, lang))
    except Exception:
        pass


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed web module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (admin_user, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating web module data...'))
    
    admin_user = context.get('admin_user')
    
    # Create themes
    themes = create_themes(workspace, stdout, style)
    
    # Create languages
    languages = create_languages(workspace, stdout, style)
    
    # Create site
    site = create_site(workspace, themes[0] if themes else None, stdout, style)
    
    # Create pages
    pages = create_pages(workspace, admin_user, stdout, style)
    
    # Create categories
    categories = create_categories(workspace, stdout, style)
    
    # Create tags
    tags = create_tags(workspace, stdout, style)
    
    # Create menus
    menus = create_menus(workspace, pages, stdout, style)
    
    # Create posts
    posts = create_posts(workspace, admin_user, categories, tags, stdout, style)
    
    # Create booking notification message templates (inbox)
    create_booking_message_templates(workspace, stdout, style)

    # Note: Media files require actual file uploads, so we skip creating media records
    if stdout:
        stdout.write(style.WARNING('↻ Media files skipped (require actual file uploads)'))
    
    summary = [
        {'label': 'Sites', 'count': Site.objects.count()},
        {'label': 'Pages', 'count': Page.objects.count()},
        {'label': 'Posts', 'count': Post.objects.count()},
        {'label': 'Menus', 'count': Menu.objects.count()},
    ]
    return {
        'themes': themes,
        'languages': languages,
        'site': site,
        'pages': pages,
        'categories': categories,
        'tags': tags,
        'menus': menus,
        'posts': posts,
        'summary': summary,
    }


def create_themes(workspace, stdout=None, style=None):
    """Create themes"""
    themes_data = [
        {
            'name': 'Default Theme',
            'code': 'default',
            'description': 'Default theme for PackGo',
            'template_path': 'themes/default',
            'primary_color': '#007bff',
            'secondary_color': '#6c757d',
            'is_active': True,
        },
        {
            'name': 'Modern Theme',
            'code': 'modern',
            'description': 'Modern theme with clean design',
            'template_path': 'themes/modern',
            'primary_color': '#28a745',
            'secondary_color': '#17a2b8',
            'is_active': True,
        },
    ]
    
    themes = []
    for theme_data in themes_data:
        theme, created = Theme.objects.get_or_create(
            workspace=workspace,
            code=theme_data['code'],
            defaults=theme_data
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created theme: {theme.name}'))
        themes.append(theme)
    
    return themes


def create_languages(workspace, stdout=None, style=None):
    """Create languages"""
    languages_data = [
        {
            'code': 'en',
            'name': 'English',
            'native_name': 'English',
            'is_default': True,
            'is_active': True,
            'order': 1,
            'is_rtl': False,
        },
        {
            'code': 'zh-hans',
            'name': 'Simplified Chinese',
            'native_name': '简体中文',
            'is_default': False,
            'is_active': True,
            'order': 2,
            'is_rtl': False,
        },
        {
            'code': 'zh-hant',
            'name': 'Traditional Chinese',
            'native_name': '繁體中文',
            'is_default': False,
            'is_active': True,
            'order': 3,
            'is_rtl': False,
        },
    ]
    
    languages = []
    for lang_data in languages_data:
        language, created = Language.objects.get_or_create(
            workspace=workspace,
            code=lang_data['code'],
            defaults=lang_data
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created language: {language.name}'))
        languages.append(language)
    
    return languages


def create_site(workspace, theme=None, stdout=None, style=None):
    """Create site"""
    site, created = Site.objects.get_or_create(
        workspace=workspace,
        domain='demo.packgo.com',
        defaults={
            'name': 'PackGo Demo Site',
            'theme': theme,
            'is_default': True,
            'is_active': True,
            'default_language': 'en',
            'languages': ['en'],
            'site_title': 'PackGo Demo',
            'site_description': 'PackGo Demo Website',
        }
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created site: {site.name}'))
    return site


def _text_block(content_html):
    """Build a text_block_v1 block for page content."""
    return {
        'id': 'block_content',
        'type': 'text_block_v1',
        'settings': {'align': 'left', 'maxWidth': '800px'},
        'data': {'content': {'en': content_html}},
    }


def _home_page_blocks():
    """
    Home page blocks: hero (full-width), then a section_v1 container with category, banner, products.
    Backend resolves source='promo' when rendering /pages/home/rendered/.
    """
    content_blocks = [
        {
            'id': 'category-grid',
            'type': 'category_grid_v1',
            'settings': {'columns': 4, 'limit': 8, 'showCount': True, 'imageHeight': '180px'},
            'data': {'source': 'promo'},
        },
        {
            'id': 'banner-grid',
            'type': 'banner_grid_v1',
            'settings': {'columns': 3, 'imageHeight': '240px', 'showOverlay': True},
            'data': {'source': 'promo', 'banners': []},
        },
        {
            'id': 'featured-products',
            'type': 'product_grid_v1',
            'settings': {'columns': 4, 'limit': 8, 'showTitle': True, 'altBackground': True},
            'data': {
                'source': 'auto',
                'productType': 'featured',
                'title': {'en': 'Featured Products', 'zh': '精选商品'},
                'emptyMessage': {'en': 'No featured products yet.', 'zh': '暂无精选商品。'},
            },
        },
        {
            'id': 'new-products',
            'type': 'product_grid_v1',
            'settings': {'columns': 4, 'limit': 4, 'showTitle': True, 'altBackground': False},
            'data': {
                'source': 'auto',
                'productType': 'new',
                'title': {'en': 'New Arrivals', 'zh': '新品上架'},
                'emptyMessage': {'en': 'No new products yet.', 'zh': '暂无新品。'},
            },
        },
        {
            'id': 'bestseller-products',
            'type': 'product_grid_v1',
            'settings': {'columns': 4, 'limit': 4, 'showTitle': True, 'altBackground': True},
            'data': {
                'source': 'auto',
                'productType': 'bestseller',
                'title': {'en': 'Bestsellers', 'zh': '畅销榜'},
                'emptyMessage': {'en': 'No bestsellers yet.', 'zh': '暂无畅销商品。'},
            },
        },
    ]
    return [
        {
            'id': 'hero-carousel',
            'type': 'hero_carousel_v1',
            'settings': {
                'autoPlay': True,
                'interval': 5000,
                'showArrows': True,
                'showDots': True,
                'height': '500px',
            },
            'data': {'source': 'promo', 'slides': []},
        },
        {
            'id': 'content-section',
            'type': 'section_v1',
            'settings': {},
            'data': {'width': 'container', 'children': content_blocks},
        },
    ]


def create_pages(workspace, admin_user, stdout=None, style=None):
    """Create pages"""
    if not admin_user:
        if stdout:
            stdout.write(style.WARNING('↻ Skipping pages creation (admin_user not available)'))
        return []

    pages_data = [
        {'title': 'Home', 'slug': 'home', 'content': '', 'status': 'published', 'blocks': _home_page_blocks()},
        {'title': 'About', 'slug': 'about', 'content': '<h1>About Us</h1><p>Learn more about PackGo.</p>', 'status': 'published'},
        {'title': 'Contact', 'slug': 'contact', 'content': '<h1>Contact Us</h1><p>Get in touch with us.</p>', 'status': 'published'},
        # Footer pages (linked from footer menu)
        {
            'title': 'Delivery',
            'slug': 'delivery',
            'content': '<h1>Delivery</h1><p>We offer reliable delivery options. Standard shipping typically takes 3–5 business days. Express options are available at checkout.</p>',
            'status': 'published',
        },
        {
            'title': 'Legal Notice',
            'slug': 'legal-notice',
            'content': '<h1>Legal Notice</h1><p>This is the legal notice and imprint for this website. Please contact us for any legal inquiries.</p>',
            'status': 'published',
        },
        {
            'title': 'Terms',
            'slug': 'terms',
            'content': '<h1>Terms and Conditions</h1><p>By using this site you agree to our terms of use. Please read them carefully.</p>',
            'status': 'published',
        },
        {
            'title': 'Secure Payment',
            'slug': 'secure-payment',
            'content': '<h1>Secure Payment</h1><p>All payments are processed securely. We support major payment methods and do not store your card details.</p>',
            'status': 'published',
        },
    ]
    pages = []
    for page_data in pages_data:
        content = page_data.get('content', '')
        blocks = page_data.get('blocks') or [_text_block(content)]
        defaults = {
            'title': page_data['title'],
            'content': content,
            'status': page_data['status'],
            'language': 'en',
            'created_by': admin_user,
            'blocks': blocks,
        }
        if page_data['status'] == 'published':
            defaults.setdefault('published_at', timezone.now())
        page, created = Page.objects.get_or_create(
            workspace=workspace,
            slug=page_data['slug'],
            defaults=defaults,
        )
        # Always update home page blocks so seed_data refreshes slide/category/pickup/products
        if page_data["slug"] == HOME_SLUG and blocks:
            page.blocks = blocks
            page.save(update_fields=["blocks", "updated_at"])
            cache.delete(get_page_rendered_cache_key(workspace.id, HOME_SLUG, "en"))
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created page: {page.title}'))
        pages.append(page)
    return pages


def create_categories(workspace, stdout=None, style=None):
    """Create categories with hierarchy for different content types"""
    categories = []
    
    # Generic categories (for posts)
    post_categories_data = [
        {'name': 'News', 'slug': 'news', 'content_type_name': 'post', 'order': 1},
        {'name': 'Updates', 'slug': 'updates', 'content_type_name': 'post', 'order': 2},
        {'name': 'Tutorials', 'slug': 'tutorials', 'content_type_name': 'post', 'order': 3},
    ]
    
    # Service categories with hierarchy
    service_categories_data = [
        {
            'name': 'Web Development',
            'slug': 'web-development',
            'content_type_name': 'service',
            'order': 1,
            'icon': 'tabler-world',
            'color': '#007bff',
            'children': [
                {'name': 'E-commerce', 'slug': 'ecommerce', 'order': 1},
                {'name': 'Corporate Websites', 'slug': 'corporate', 'order': 2},
            ]
        },
        {
            'name': 'Mobile Apps',
            'slug': 'mobile-apps',
            'content_type_name': 'service',
            'order': 2,
            'icon': 'tabler-device-mobile',
            'color': '#28a745',
            'children': [
                {'name': 'iOS Development', 'slug': 'ios', 'order': 1},
                {'name': 'Android Development', 'slug': 'android', 'order': 2},
            ]
        },
    ]
    
    # Project categories
    project_categories_data = [
        {'name': 'Completed', 'slug': 'completed', 'content_type_name': 'project', 'order': 1, 'icon': 'tabler-check', 'color': '#28a745'},
        {'name': 'In Progress', 'slug': 'in-progress', 'content_type_name': 'project', 'order': 2, 'icon': 'tabler-clock', 'color': '#ffc107'},
        {'name': 'Planned', 'slug': 'planned', 'content_type_name': 'project', 'order': 3, 'icon': 'tabler-calendar', 'color': '#17a2b8'},
    ]
    
    # FAQ categories
    faq_categories_data = [
        {
            'name': 'Product',
            'slug': 'product',
            'content_type_name': 'faq',
            'order': 1,
            'icon': 'tabler-package',
            'color': '#6f42c1',
            'children': [
                {'name': 'Pricing', 'slug': 'pricing', 'order': 1},
                {'name': 'Features', 'slug': 'features', 'order': 2},
            ]
        },
        {'name': 'Support', 'slug': 'support', 'content_type_name': 'faq', 'order': 2, 'icon': 'tabler-help', 'color': '#dc3545'},
    ]
    
    # Create post categories
    for cat_data in post_categories_data:
        category, created = Category.objects.get_or_create(
            workspace=workspace,
            slug=cat_data['slug'],
            language='en',
            defaults={
                'name': cat_data['name'],
                'content_type_name': cat_data['content_type_name'],
                'order': cat_data['order'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created category: {category.name}'))
        categories.append(category)
    
    # Create service categories with hierarchy
    for parent_data in service_categories_data:
        children_data = parent_data.pop('children', [])
        parent, created = Category.objects.get_or_create(
            workspace=workspace,
            slug=parent_data['slug'],
            language='en',
            defaults={
                'name': parent_data['name'],
                'content_type_name': parent_data['content_type_name'],
                'order': parent_data['order'],
                'icon': parent_data.get('icon', ''),
                'color': parent_data.get('color', ''),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created category: {parent.name}'))
        categories.append(parent)
        
        # Create children
        for child_data in children_data:
            child, created = Category.objects.get_or_create(
                workspace=workspace,
                slug=child_data['slug'],
                language='en',
                defaults={
                    'name': child_data['name'],
                    'parent': parent,
                    'content_type_name': parent_data['content_type_name'],
                    'order': child_data['order'],
                    'is_active': True,
                }
            )
            if created and stdout:
                stdout.write(style.SUCCESS(f'✓ Created category: {child.name} (child of {parent.name})'))
            categories.append(child)
    
    # Create project categories
    for cat_data in project_categories_data:
        category, created = Category.objects.get_or_create(
            workspace=workspace,
            slug=cat_data['slug'],
            language='en',
            defaults={
                'name': cat_data['name'],
                'content_type_name': cat_data['content_type_name'],
                'order': cat_data['order'],
                'icon': cat_data.get('icon', ''),
                'color': cat_data.get('color', ''),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created category: {category.name}'))
        categories.append(category)
    
    # Create FAQ categories with hierarchy
    for parent_data in faq_categories_data:
        children_data = parent_data.pop('children', [])
        parent, created = Category.objects.get_or_create(
            workspace=workspace,
            slug=parent_data['slug'],
            language='en',
            defaults={
                'name': parent_data['name'],
                'content_type_name': parent_data['content_type_name'],
                'order': parent_data['order'],
                'icon': parent_data.get('icon', ''),
                'color': parent_data.get('color', ''),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created category: {parent.name}'))
        categories.append(parent)
        
        # Create children
        for child_data in children_data:
            child, created = Category.objects.get_or_create(
                workspace=workspace,
                slug=child_data['slug'],
                language='en',
                defaults={
                    'name': child_data['name'],
                    'parent': parent,
                    'content_type_name': parent_data['content_type_name'],
                    'order': child_data['order'],
                    'is_active': True,
                }
            )
            if created and stdout:
                stdout.write(style.SUCCESS(f'✓ Created category: {child.name} (child of {parent.name})'))
            categories.append(child)
    
    return categories


def create_tags(workspace, stdout=None, style=None):
    """Create tags for flexible content organization"""
    tags_data = [
        {'name': 'Featured', 'slug': 'featured'},
        {'name': 'Popular', 'slug': 'popular'},
        {'name': 'New', 'slug': 'new'},
        {'name': 'Technology', 'slug': 'technology'},
        {'name': 'Business', 'slug': 'business'},
        {'name': 'Design', 'slug': 'design'},
        {'name': 'Development', 'slug': 'development'},
    ]
    
    tags = []
    for tag_data in tags_data:
        tag, created = Tag.objects.get_or_create(
            workspace=workspace,
            slug=tag_data['slug'],
            language='en',
            defaults={
                'name': tag_data['name'],
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created tag: {tag.name}'))
        tags.append(tag)
    
    return tags


def create_menus(workspace, pages, stdout=None, style=None):
    """Create menus and menu items"""
    menus = []
    
    # Create main menu
    main_menu, created = Menu.objects.get_or_create(
        workspace=workspace,
        slug='main-menu',
        defaults={
            'name': 'Main Menu',
            'location': 'header',
            'is_active': True,
            'language': 'en',
        }
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created menu: {main_menu.name}'))
    menus.append(main_menu)
    
    # Create menu items for main menu
    if pages and created:
        for i, page in enumerate(pages[:3]):  # First 3 pages
            MenuItem.objects.get_or_create(
                menu=main_menu,
                title=page.title,
                defaults={
                    'url': f'/{page.slug}',
                    'order': i + 1,
                    'is_active': True,
                }
            )
    
    # Create footer menu
    footer_menu, created = Menu.objects.get_or_create(
        workspace=workspace,
        slug='footer-menu',
        defaults={
            'name': 'Footer Menu',
            'location': 'footer',
            'is_active': True,
            'language': 'en',
        }
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created menu: {footer_menu.name}'))
    menus.append(footer_menu)

    # Footer menu items (Our Company section)
    footer_items = [
        ('Delivery', '/delivery', 1),
        ('Legal Notice', '/legal-notice', 2),
        ('Terms', '/terms', 3),
        ('About Us', '/about', 4),
        ('Secure Payment', '/secure-payment', 5),
    ]
    for title, url, order in footer_items:
        MenuItem.objects.get_or_create(
            menu=footer_menu,
            url=url,
            defaults={
                'title': title,
                'order': order,
                'is_active': True,
                'open_in_new_tab': False,
            }
        )

    return menus


def create_booking_message_templates(workspace, stdout=None, style=None):
    """Create message templates for booking notifications (used when admin confirms)."""
    try:
        from bfg.inbox.models import MessageTemplate
    except ImportError:
        if stdout:
            stdout.write(style.WARNING('↻ Inbox module not available, skip booking templates'))
        return
    data = {
        'name': 'Booking Confirmed',
        'code': 'booking_confirmed',
        'event': 'booking.status_changed',
        'language': 'en',
        'email_enabled': True,
        'email_subject': 'Booking confirmed - {{ slot_display }}',
        'email_body': '''Your booking has been confirmed.

Time slot: {{ slot_display }}
Booking ID: {{ booking_id }}

Thank you.
''',
        'app_message_enabled': True,
        'app_message_title': 'Booking Confirmed',
        'app_message_body': 'Your booking for {{ slot_display }} has been confirmed. Booking #{{ booking_id }}',
        'sms_enabled': False,
        'push_enabled': False,
        'is_active': True,
    }
    tpl, created = MessageTemplate.objects.get_or_create(
        workspace=workspace,
        code=data['code'],
        language=data['language'],
        defaults=data,
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created message template: {tpl.name}'))


def create_posts(workspace, admin_user, categories, tags, stdout=None, style=None):
    """Create blog posts"""
    if not admin_user:
        if stdout:
            stdout.write(style.WARNING('↻ Skipping posts creation (admin_user not available)'))
        return []
    
    posts_data = [
        {
            'title': 'Welcome to BFG Blog',
            'slug': 'welcome-to-packgo-blog',
            'excerpt': 'Learn about our new freight forwarding platform',
            'content': '<h1>Welcome to BFG Blog</h1><p>We are excited to launch our new blog where we will share updates, tips, and insights about freight forwarding.</p>',
            'status': 'published',
        },
        {
            'title': 'How to Track Your Shipment',
            'slug': 'how-to-track-your-shipment',
            'excerpt': 'A step-by-step guide to tracking your packages',
            'content': '<h1>How to Track Your Shipment</h1><p>Tracking your shipment is easy with PackGo. Here is a comprehensive guide.</p>',
            'status': 'published',
        },
        {
            'title': 'Understanding Freight Costs',
            'slug': 'understanding-freight-costs',
            'excerpt': 'Learn what factors affect your shipping costs',
            'content': '<h1>Understanding Freight Costs</h1><p>Freight costs depend on many factors. Let us break them down for you.</p>',
            'status': 'published',
        },
    ]
    
    posts = []
    for i, post_data in enumerate(posts_data):
        # Get category for this post (use post categories from create_categories)
        category = next((c for c in categories if c.content_type_name == 'post'), None) if categories else None
        
        post, created = Post.objects.get_or_create(
            workspace=workspace,
            slug=post_data['slug'],
            defaults={
                'title': post_data['title'],
                'excerpt': post_data['excerpt'],
                'content': post_data['content'],
                'status': post_data['status'],
                'language': 'en',
                'author': admin_user,
                'category': category,
                'published_at': timezone.now() if post_data['status'] == 'published' else None,
            }
        )
        
        if created:
            # Add tags
            if tags and i < len(tags):
                post.tags.add(tags[i])
                if i == 0 and len(tags) > 1:  # Add 'featured' tag to first post
                    featured_tag = next((t for t in tags if t.slug == 'featured'), None)
                    if featured_tag:
                        post.tags.add(featured_tag)
            
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created post: {post.title}'))
        posts.append(post)
    
    return posts


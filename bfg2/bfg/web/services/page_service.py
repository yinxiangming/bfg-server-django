"""
BFG Web Module Services

Page management service with caching support.
Cache policy: disabled in DEBUG; home and category pages cacheable with per-type TTL.
"""

from typing import Any, Dict, List, Optional
from django.db import transaction
from django.db.models import QuerySet
from django.utils.text import slugify
from django.utils import timezone
from django.core.cache import cache
from bfg.core.services import BaseService
from bfg.web.exceptions import PageNotFound
from bfg.web.models import Page

# Cache key prefix; single place for key format
PAGE_RENDERED_CACHE_PREFIX = "page_rendered"

# TTL per page type (seconds). Only home and category are cacheable.
PAGE_CACHE_TTL_HOME = 60 * 60  # 1 hour
PAGE_CACHE_TTL_CATEGORY = 60 * 30  # 30 min
PAGE_CACHE_CATEGORY_SLUG_PREFIX = "category"

HOME_SLUG = "home"


def get_page_rendered_cache_key(workspace_id: int, slug: str, language: str) -> str:
    """Generate cache key for rendered page. Use this everywhere to avoid key drift."""
    return f"{PAGE_RENDERED_CACHE_PREFIX}:{workspace_id}:{slug}:{language}"


def is_cache_enabled() -> bool:
    """Cache is disabled in development (DEBUG)."""
    from django.conf import settings
    return not getattr(settings, "DEBUG", False)


def is_home_slug(slug: str) -> bool:
    """True if slug is the home page."""
    return slug == HOME_SLUG


def is_page_cacheable(slug: str) -> bool:
    """True if this slug is allowed to be cached (home or category-type)."""
    if not slug:
        return False
    if slug == HOME_SLUG:
        return True
    if slug == PAGE_CACHE_CATEGORY_SLUG_PREFIX or slug.startswith(
        f"{PAGE_CACHE_CATEGORY_SLUG_PREFIX}-"
    ):
        return True
    return False


def get_page_cache_ttl(slug: str) -> int:
    """TTL in seconds for the given slug. 0 means do not cache."""
    if not is_cache_enabled() or not is_page_cacheable(slug):
        return 0
    if slug == HOME_SLUG:
        return PAGE_CACHE_TTL_HOME
    if slug == PAGE_CACHE_CATEGORY_SLUG_PREFIX or slug.startswith(
        f"{PAGE_CACHE_CATEGORY_SLUG_PREFIX}-"
    ):
        return PAGE_CACHE_TTL_CATEGORY
    return 0


def invalidate_home_page_cache_for_workspace(
    workspace_id: int, languages: Optional[List[str]] = None
) -> None:
    """
    Invalidate rendered cache for the home page of a workspace.
    Call this when promo/CampaignDisplay/Campaign data changes so storefront gets fresh data.
    """
    if languages is None:
        languages = ["en", "zh"]
    for lang in languages:
        cache.delete(get_page_rendered_cache_key(workspace_id, HOME_SLUG, lang))


def invalidate_page_rendered_cache(
    workspace_id: int, slug: str, languages: Optional[List[str]] = None
) -> None:
    """Invalidate rendered cache for a specific page slug and languages."""
    if languages is None:
        languages = ["en", "zh"]
    for lang in languages:
        cache.delete(get_page_rendered_cache_key(workspace_id, slug, lang))


class PageService(BaseService):
    """
    Page management service
    
    Handles CMS page creation, updates, and publishing
    """
    
    @transaction.atomic
    def create_page(self, title: str, content: str, **kwargs: Any) -> Page:
        """
        Create new page with auto-generated slug
        
        Args:
            title: Page title
            content: Page content (HTML)
            **kwargs: Additional page fields
            
        Returns:
            Page: Created page instance
        """
        # Generate slug if not provided
        slug = kwargs.get('slug')
        if not slug:
            slug = slugify(title)
            # Ensure uniqueness
            base_slug = slug
            counter = 1
            while Page.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
        
        # Create page
        page = Page.objects.create(
            workspace=self.workspace,
            title=title,
            slug=slug,
            content=content,
            excerpt=kwargs.get('excerpt', ''),
            parent=kwargs.get('parent'),
            template=kwargs.get('template', 'default'),
            meta_title=kwargs.get('meta_title', title),
            meta_description=kwargs.get('meta_description', ''),
            meta_keywords=kwargs.get('meta_keywords', ''),
            status=kwargs.get('status', 'draft'),
            is_featured=kwargs.get('is_featured', False),
            allow_comments=kwargs.get('allow_comments', False),
            order=kwargs.get('order', 100),
            language=kwargs.get('language', 'en'),
            created_by=self.user,
        )
        
        return page
    
    def get_page_by_slug(self, slug: str, language: str = 'en') -> Page:
        """
        Get page by slug
        
        Args:
            slug: Page slug
            language: Language code
            
        Returns:
            Page: Page instance
            
        Raises:
            PageNotFound: If page doesn't exist
        """
        try:
            page = Page.objects.select_related('parent', 'created_by').get(
                workspace=self.workspace,
                slug=slug,
                language=language
            )
            return page
        except Page.DoesNotExist:
            raise PageNotFound(f"Page with slug '{slug}' not found")
    
    def update_page(self, page: Page, **kwargs: Any) -> Page:
        """
        Update page content and metadata
        
        Args:
            page: Page instance
            **kwargs: Fields to update
            
        Returns:
            Page: Updated page instance
        """
        self.validate_workspace_access(page)
        
        for key, value in kwargs.items():
            if hasattr(page, key) and key not in ['id', 'workspace', 'created_by', 'created_at']:
                setattr(page, key, value)
        
        page.save()
        return page
    
    @transaction.atomic
    def publish_page(self, page: Page) -> Page:
        """
        Publish page
        
        Args:
            page: Page instance
            
        Returns:
            Page: Updated page instance
        """
        self.validate_workspace_access(page)
        
        page.status = 'published'
        if not page.published_at:
            page.published_at = timezone.now()
        page.save()
        
        return page
    
    @transaction.atomic
    def unpublish_page(self, page: Page) -> Page:
        """
        Unpublish page (set to draft)
        
        Args:
            page: Page instance
            
        Returns:
            Page: Updated page instance
        """
        self.validate_workspace_access(page)
        
        page.status = 'draft'
        page.save()
        
        return page
    
    def get_page_tree(self, language: str = 'en') -> QuerySet[Page]:
        """
        Get hierarchical page structure
        
        Args:
            language: Language code
            
        Returns:
            QuerySet: Root pages with prefetched children
        """
        return Page.objects.filter(
            workspace=self.workspace,
            language=language,
            parent__isnull=True
        ).prefetch_related('children').order_by('order', 'title')
    
    def _get_cache_key(self, slug: str, language: str) -> str:
        """Generate cache key for rendered page (delegates to module-level key)."""
        return get_page_rendered_cache_key(self.workspace.id, slug, language)

    def get_rendered_page(
        self, slug: str, language: str = "en", request: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Get rendered page with resolved blocks (with caching).

        When slug is home and request is provided, blocks with data.source='promo'
        are filled from marketing CampaignDisplay (slides, category_entry, featured).
        Cache is disabled in DEBUG; only home and category-type slugs are cached.
        """
        cache_key = self._get_cache_key(slug, language)
        use_cache = is_cache_enabled() and is_page_cacheable(slug)

        if use_cache:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                return cached_data

        # Fetch page; fallback to en, then to any language for this slug (e.g. home only in zh-hans)
        try:
            page = self.get_page_by_slug(slug, language)
        except PageNotFound:
            page = None
            for fallback_lang in ("en", "zh-hans", "zh"):
                if fallback_lang == language:
                    continue
                try:
                    page = self.get_page_by_slug(slug, fallback_lang)
                    break
                except PageNotFound:
                    pass
            if page is None:
                page = (
                    Page.objects.filter(
                        workspace=self.workspace,
                        slug=slug,
                        status="published",
                    )
                    .order_by("order", "id")
                    .first()
                )
                if page is None:
                    raise PageNotFound(f"Page with slug '{slug}' not found")

        # Only render published pages
        if page.status != "published":
            raise PageNotFound(f"Page '{slug}' is not published")

        # Resolve blocks
        from bfg.web.services.block_service import BlockService

        block_service = BlockService(workspace=self.workspace, user=self.user)
        blocks = page.blocks or []
        # Fallback: use legacy content as a single text block when no blocks (except home)
        if not blocks and (page.content or "").strip() and not is_home_slug(page.slug):
            blocks = [
                {
                    "id": "block_content",
                    "type": "text_block_v1",
                    "settings": {"align": "left", "maxWidth": "800px"},
                    "data": {"content": {"en": page.content}},
                }
            ]
        resolved_blocks = block_service.resolve_all_blocks(blocks)

        # Resolve promo data for home page blocks (source='promo')
        if is_home_slug(slug) and request:
            resolved_blocks = self._resolve_home_promo_blocks(resolved_blocks, request)

        # Build rendered data
        rendered_data = {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "excerpt": page.excerpt,
            "blocks": resolved_blocks,
            "meta_title": page.meta_title or page.title,
            "meta_description": page.meta_description,
            "meta_keywords": page.meta_keywords,
            "language": page.language,
            "published_at": page.published_at.isoformat() if page.published_at else None,
        }

        ttl = get_page_cache_ttl(slug)
        if use_cache and ttl > 0:
            cache.set(cache_key, rendered_data, ttl)

        return rendered_data

    def _resolve_home_promo_blocks(
        self, blocks: List[Dict[str, Any]], request: Any
    ) -> List[Dict[str, Any]]:
        """Fill blocks with data.source='promo' using marketing CampaignDisplay data."""
        try:
            from bfg.marketing.promo_views import get_promo_available
        except ImportError:
            return blocks
        promo = get_promo_available(self.workspace, request)
        slides = promo.get('slides') or []
        featured_categories = promo.get('featured_categories') or []

        category_entry = [x for x in featured_categories if x.get('display_type') == 'category_entry']
        featured_items = [x for x in featured_categories if x.get('display_type') == 'featured']

        for block in blocks:
            block_type = block.get('type', '')
            if block_type == 'section_v1':
                children = (block.get('data') or {}).get('children') or []
                block['data'] = dict(block.get('data') or {})
                block['data']['children'] = self._resolve_home_promo_blocks(children, request)
                continue
            data = block.get('data') or {}
            if data.get('source') != 'promo':
                continue
            if block_type == 'hero_carousel_v1':
                # Client expects: image, title?, subtitle?, buttonText?, buttonLink?
                block['data'] = dict(data)
                block['data']['slides'] = [
                    {
                        'image': s.get('image') or '',
                        'title': {'en': s.get('title') or '', 'zh': s.get('title') or ''},
                        'subtitle': {'en': s.get('subtitle') or '', 'zh': s.get('subtitle') or ''},
                        'buttonText': {'en': 'Shop Now', 'zh': '立即选购'} if s.get('link_url') else None,
                        'buttonLink': s.get('link_url') or None,
                    }
                    for s in sorted(slides, key=lambda x: x.get('order', 0))
                ]
            elif block_type == 'category_grid_v1':
                # Client CategoryGridV1 uses resolvedData: [{ name, slug, image, product_count }]
                # Prefer CampaignDisplay.title for name; fallback to category.name
                block['resolvedData'] = [
                    {
                        'name': (item.get('title') or '').strip() or item.get('category', {}).get('name', ''),
                        'slug': item.get('category', {}).get('slug', ''),
                        'image': item.get('image') or item.get('category', {}).get('image', ''),
                        'image_url': item.get('image') or item.get('category', {}).get('image', ''),
                        'product_count': 0,
                    }
                    for item in sorted(category_entry, key=lambda x: x.get('order', 0))
                ]
            elif block_type == 'banner_grid_v1':
                # Client expects: banners: [{ image, title?: {en,zh}, link? }]
                block['data'] = dict(data)
                block['data']['banners'] = [
                    {
                        'image': item.get('image') or item.get('category', {}).get('image', ''),
                        'title': {
                            'en': item.get('title') or item.get('category', {}).get('name', ''),
                            'zh': item.get('title') or item.get('category', {}).get('name', ''),
                        },
                        'link': item.get('link_url') or (
                            f"/category/{item.get('category', {}).get('slug', '')}"
                            if item.get('category', {}).get('slug') else ''
                        ),
                    }
                    for item in sorted(featured_items, key=lambda x: x.get('order', 0))
                ]
        return blocks
    
    def invalidate_page_cache(self, page: Page) -> None:
        """
        Invalidate cache for a page
        
        Args:
            page: Page instance
        """
        cache_key = self._get_cache_key(page.slug, page.language)
        cache.delete(cache_key)
    
    @transaction.atomic
    def update_page_blocks(self, page: Page, blocks: List[Dict[str, Any]]) -> Page:
        """
        Update page blocks configuration
        
        Args:
            page: Page instance
            blocks: New blocks configuration
            
        Returns:
            Updated page
        """
        self.validate_workspace_access(page)
        
        # Validate blocks
        from bfg.web.services.block_service import BlockService
        block_service = BlockService(workspace=self.workspace, user=self.user)
        validation = block_service.validate_blocks(blocks)
        
        if not validation['valid']:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'blocks': validation['errors']})
        
        page.blocks = blocks
        page.save(update_fields=['blocks', 'updated_at'])
        
        # Invalidate cache
        self.invalidate_page_cache(page)
        
        return page
    
    def export_page_config(self, page: Page) -> Dict[str, Any]:
        """
        Export page configuration for backup/import
        
        Args:
            page: Page instance
            
        Returns:
            Dict with exportable page config
        """
        return {
            'version': '1.0',
            'exported_at': timezone.now().isoformat(),
            'page': {
                'title': page.title,
                'slug': page.slug,
                'template': page.template,
                'blocks': page.blocks,
                'meta_title': page.meta_title,
                'meta_description': page.meta_description,
                'meta_keywords': page.meta_keywords,
                'language': page.language,
            }
        }
    
    @transaction.atomic
    def import_page_config(self, config: Dict[str, Any], slug: Optional[str] = None) -> Page:
        """
        Import page configuration
        
        Args:
            config: Exported page config
            slug: Optional custom slug (overrides config slug)
            
        Returns:
            Created/updated page
        """
        page_data = config.get('page', {})
        target_slug = slug or page_data.get('slug')
        
        if not target_slug:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'slug': 'Slug is required'})
        
        # Try to find existing page
        try:
            page = self.get_page_by_slug(target_slug, page_data.get('language', 'en'))
            # Update existing
            page.blocks = page_data.get('blocks', [])
            page.meta_title = page_data.get('meta_title', '')
            page.meta_description = page_data.get('meta_description', '')
            page.meta_keywords = page_data.get('meta_keywords', '')
            page.save()
        except PageNotFound:
            # Create new
            page = self.create_page(
                title=page_data.get('title', target_slug),
                content='',  # Blocks-based pages don't need content
                slug=target_slug,
                template=page_data.get('template', 'builder'),
                language=page_data.get('language', 'en'),
                meta_title=page_data.get('meta_title', ''),
                meta_description=page_data.get('meta_description', ''),
                meta_keywords=page_data.get('meta_keywords', ''),
            )
            page.blocks = page_data.get('blocks', [])
            page.save(update_fields=['blocks'])
        
        # Invalidate cache
        self.invalidate_page_cache(page)
        
        return page

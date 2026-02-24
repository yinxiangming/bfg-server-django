"""
BFG Web Module Services

Post management service
"""

from typing import Any, Optional, List
from datetime import datetime
from django.db import transaction
from django.db.models import QuerySet
from django.utils.text import slugify
from django.utils import timezone
from bfg.core.services import BaseService
from bfg.web.exceptions import PostNotFound
from bfg.web.models import Post, Category, Tag


class PostService(BaseService):
    """
    Post management service
    
    Handles blog post creation, updates, and publishing workflow
    """
    
    @transaction.atomic
    def create_post(self, title: str, content: str, **kwargs: Any) -> Post:
        """
        Create new blog post
        
        Args:
            title: Post title
            content: Post content (HTML)
            **kwargs: Additional post fields
            
        Returns:
            Post: Created post instance
        """
        # Generate slug if not provided
        slug = kwargs.get('slug')
        if not slug:
            slug = slugify(title)
            # Ensure uniqueness within workspace and language
            base_slug = slug
            counter = 1
            language = kwargs.get('language', 'en')
            while Post.objects.filter(
                workspace=self.workspace,
                slug=slug,
                language=language
            ).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
        
        # Create post
        post = Post.objects.create(
            workspace=self.workspace,
            title=title,
            slug=slug,
            content=content,
            excerpt=kwargs.get('excerpt', ''),
            featured_image=kwargs.get('featured_image'),
            category=kwargs.get('category'),
            meta_title=kwargs.get('meta_title', title),
            meta_description=kwargs.get('meta_description', ''),
            status=kwargs.get('status', 'draft'),
            allow_comments=kwargs.get('allow_comments', True),
            language=kwargs.get('language', 'en'),
            author=self.user,
        )
        
        # Add tags if provided
        if 'tags' in kwargs:
            post.tags.set(kwargs['tags'])
        
        return post
    
    def get_post_by_slug(self, slug: str, language: str = 'en') -> Post:
        """
        Get post by slug
        
        Args:
            slug: Post slug
            language: Language code
            
        Returns:
            Post: Post instance
            
        Raises:
            PostNotFound: If post doesn't exist
        """
        try:
            post = Post.objects.select_related(
                'category', 'author'
            ).prefetch_related('tags').get(
                workspace=self.workspace,
                slug=slug,
                language=language
            )
            return post
        except Post.DoesNotExist:
            raise PostNotFound(f"Post with slug '{slug}' not found")
    
    def update_post(self, post: Post, **kwargs: Any) -> Post:
        """
        Update post content and metadata
        
        Args:
            post: Post instance
            **kwargs: Fields to update
            
        Returns:
            Post: Updated post instance
        """
        self.validate_workspace_access(post)
        
        # Handle tags separately
        tags = kwargs.pop('tags', None)
        
        for key, value in kwargs.items():
            if hasattr(post, key) and key not in ['id', 'workspace', 'author', 'created_at']:
                setattr(post, key, value)
        
        post.save()
        
        # Update tags if provided
        if tags is not None:
            post.tags.set(tags)
        
        return post
    
    @transaction.atomic
    def publish_post(self, post: Post) -> Post:
        """
        Publish post immediately
        
        Args:
            post: Post instance
            
        Returns:
            Post: Updated post instance
        """
        self.validate_workspace_access(post)
        
        post.status = 'published'
        if not post.published_at:
            post.published_at = timezone.now()
        post.save()
        
        return post
    
    @transaction.atomic
    def schedule_post(self, post: Post, publish_at: datetime) -> Post:
        """
        Schedule post for future publishing
        
        Args:
            post: Post instance
            publish_at: Datetime to publish
            
        Returns:
            Post: Updated post instance
        """
        self.validate_workspace_access(post)
        
        post.published_at = publish_at
        # Keep as draft until publish time
        post.status = 'draft'
        post.save()
        
        return post
    
    def get_published_posts(
        self, 
        category: Optional[Category] = None, 
        tag: Optional[Tag] = None, 
        language: str = 'en', 
        limit: Optional[int] = None
    ) -> QuerySet[Post]:
        """
        Get published posts with optional filters
        
        Args:
            category: Filter by category
            tag: Filter by tag
            language: Language code
            limit: Maximum number of posts
            
        Returns:
            QuerySet: Published posts
        """
        queryset = Post.objects.filter(
            workspace=self.workspace,
            status='published',
            language=language,
            published_at__lte=timezone.now()
        ).select_related('category', 'author').prefetch_related('tags')
        
        if category:
            queryset = queryset.filter(category=category)
        
        if tag:
            queryset = queryset.filter(tags=tag)
        
        if limit:
            queryset = queryset[:limit]
        
        return queryset.order_by('-published_at')

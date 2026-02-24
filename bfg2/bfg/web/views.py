"""
BFG Web Module API Views

ViewSets for web module
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404 as django_get_object_or_404

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff
from bfg.web.models import (
    Site, Theme, Language, Page, Post, Media, Category, Tag, Menu, Inquiry,
    BookingTimeSlot, Booking,
    NewsletterSubscription, NewsletterTemplate, NewsletterSend, NewsletterSendLog,
)
from bfg.web.serializers import (
    SiteSerializer,
    ThemeSerializer,
    LanguageSerializer,
    PageListSerializer,
    PageDetailSerializer,
    PageRenderedSerializer,
    PostListSerializer,
    PostDetailSerializer,
    MediaSerializer,
    CategorySerializer,
    TagSerializer,
    MenuSerializer,
    InquiryListSerializer,
    InquiryDetailSerializer,
    InquiryCreateSerializer,
    BookingTimeSlotSerializer,
    BookingSerializer,
    NewsletterSubscriptionCreateSerializer,
    NewsletterSubscriptionListSerializer,
    NewsletterSubscriptionDetailSerializer,
    NewsletterSubscriptionUpdateSerializer,
    NewsletterTemplateSerializer,
    NewsletterSendSerializer,
    NewsletterSendLogSerializer,
)
from bfg.web.services import SiteService, PageService, PostService, MediaService, BlockService, InquiryService, NewsletterService, SiteConfigService
from bfg.core.events import global_dispatcher


def get_workspace(request):
    """Safely get workspace from request"""
    workspace = getattr(request, 'workspace', None)
    if not workspace:
        from rest_framework.exceptions import NotFound
        raise NotFound("No workspace available. Please ensure a workspace exists and is active.")
    return workspace


class SiteViewSet(viewsets.ModelViewSet):
    """
    Site management ViewSet
    
    Only admins can create/update/delete sites
    """
    serializer_class = SiteSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]  # Restored to IsWorkspaceAdmin (now allows superuser)
    
    def get_queryset(self):
        """Get sites for current workspace"""
        workspace = get_workspace(self.request)
        return Site.objects.filter(
            workspace=workspace
        ).select_related('theme')
    
    def perform_create(self, serializer):
        """Create site using service"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set site as default"""
        site = self.get_object()
        workspace = get_workspace(request)
        service = SiteService(
            workspace=workspace,
            user=request.user
        )
        site = service.set_default_site(site)
        serializer = self.get_serializer(site)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='export')
    def export_site(self, request):
        """Export current workspace site data (Site, Theme, Pages, Menus) as JSON for backup/restore."""
        workspace = get_workspace(request)
        service = SiteConfigService(workspace=workspace, user=request.user)
        include_theme = request.query_params.get('include_theme', 'true').lower() != 'false'
        data = service.export_site(include_theme=include_theme)
        return Response(data)

    @action(detail=False, methods=['post'], url_path='import')
    def import_site(self, request):
        """Import site config JSON (merge or replace). Body: { \"config\": {...}, \"mode\": \"merge\"|\"replace\" }."""
        workspace = get_workspace(request)
        config = request.data.get('config') or request.data
        mode = (request.data.get('mode') or 'merge').strip().lower()
        if mode not in ('merge', 'replace'):
            return Response({'detail': 'mode must be merge or replace'}, status=status.HTTP_400_BAD_REQUEST)
        service = SiteConfigService(workspace=workspace, user=request.user)
        try:
            result = service.load_from_config(config, created_by_user=request.user, mode=mode)
            return Response({
                'detail': 'Import completed',
                'site': result.get('site').name if result.get('site') else None,
                'pages_count': len(result.get('pages', [])),
            })
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PageViewSet(viewsets.ModelViewSet):
    """
    Page management ViewSet

    Public can view published pages, staff can manage all pages.
    Retrieve supports both pk (numeric) and slug for admin and public URLs.
    """
    lookup_field = 'slug'

    def get_object(self):
        """Resolve by pk when URL kwarg is numeric, else by slug (for admin vs public URLs)."""
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]
        if isinstance(lookup_value, str) and lookup_value.isdigit():
            filter_kwargs = {'pk': int(lookup_value)}
        else:
            filter_kwargs = {self.lookup_field: lookup_value}
        return django_get_object_or_404(queryset, **filter_kwargs)

    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'retrieve':
            return PageDetailSerializer
        return PageListSerializer
    
    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve', 'rendered']:
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceStaff()]
    
    def get_queryset(self):
        """Get pages based on permissions"""
        workspace = get_workspace(self.request)
        user = self.request.user
        
        queryset = Page.objects.filter(workspace=workspace).select_related('parent', 'created_by')
        
        # Non-staff can only see published pages
        if not getattr(self.request, 'is_staff_member', False):
            queryset = queryset.filter(status='published')
        
        # Filter by parent if provided
        parent_id = self.request.query_params.get('parent')
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)

        # Filter by language only when ?lang= is provided; omit param to list all languages (e.g. admin)
        lang_param = self.request.query_params.get('lang')
        if lang_param is not None:
            queryset = queryset.filter(language=lang_param)

        return queryset.order_by('order', 'title')
    
    def perform_create(self, serializer):
        """Create page using service"""
        workspace = get_workspace(self.request)
        service = PageService(
            workspace=workspace,
            user=self.request.user
        )
        page = service.create_page(
            title=serializer.validated_data['title'],
            content=serializer.validated_data.get('content', ''),
            **{k: v for k, v in serializer.validated_data.items() if k not in ['title', 'content']}
        )
        serializer.instance = page
    
    @action(detail=True, methods=['post'])
    def publish(self, request, slug=None):
        """Publish page"""
        page = self.get_object()
        workspace = get_workspace(request)
        service = PageService(
            workspace=workspace,
            user=request.user
        )
        page = service.publish_page(page)
        serializer = self.get_serializer(page)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def tree(self, request):
        """Get hierarchical page structure"""
        workspace = get_workspace(request)
        service = PageService(
            workspace=workspace,
            user=request.user
        )
        language = request.query_params.get('lang', 'en')
        pages = service.get_page_tree(language)
        serializer = PageListSerializer(pages, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def rendered(self, request, slug=None):
        """Get rendered page with resolved blocks for public display"""
        workspace = get_workspace(request)
        service = PageService(
            workspace=workspace,
            user=request.user if request.user.is_authenticated else None
        )
        language = request.query_params.get('lang', 'en')
        
        try:
            rendered_data = service.get_rendered_page(slug, language, request=request)
            return Response(rendered_data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['put'])
    def blocks(self, request, slug=None):
        """Update page blocks configuration"""
        page = self.get_object()
        workspace = get_workspace(request)
        service = PageService(
            workspace=workspace,
            user=request.user
        )
        
        blocks = request.data.get('blocks', [])
        page = service.update_page_blocks(page, blocks)
        serializer = PageDetailSerializer(page)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def export(self, request, slug=None):
        """Export page configuration"""
        page = self.get_object()
        workspace = get_workspace(request)
        service = PageService(
            workspace=workspace,
            user=request.user
        )
        config = service.export_page_config(page)
        return Response(config)
    
    @action(detail=False, methods=['post'], url_path='import')
    def import_config(self, request):
        """Import page configuration"""
        workspace = get_workspace(request)
        service = PageService(
            workspace=workspace,
            user=request.user
        )
        
        config = request.data.get('config', {})
        slug = request.data.get('slug')
        
        if not config:
            return Response(
                {'error': 'Config is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        page = service.import_page_config(config, slug)
        serializer = PageDetailSerializer(page)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PostViewSet(viewsets.ModelViewSet):
    """
    Blog post management ViewSet
    
    Public can view published posts, staff can manage all posts
    """
    lookup_field = 'slug'
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'retrieve':
            return PostDetailSerializer
        return PostListSerializer
    
    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceStaff()]
    
    def get_queryset(self):
        """Get posts based on permissions"""
        workspace = get_workspace(self.request)
        
        queryset = Post.objects.filter(workspace=workspace).select_related(
            'category', 'author'
        ).prefetch_related('tags')
        
        # Non-staff can only see published posts
        if not getattr(self.request, 'is_staff_member', False):
            from django.utils import timezone
            queryset = queryset.filter(
                status='published',
                published_at__lte=timezone.now()
            )
        
        # Filter by category
        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        
        # Filter by tag
        tag_id = self.request.query_params.get('tag')
        if tag_id:
            queryset = queryset.filter(tags__id=tag_id)
        
        # Filter by language
        language = self.request.query_params.get('lang', 'en')
        queryset = queryset.filter(language=language)
        
        return queryset.order_by('-published_at')
    
    def perform_create(self, serializer):
        """Create post using service"""
        workspace = get_workspace(self.request)
        service = PostService(
            workspace=workspace,
            user=self.request.user
        )
        
        # Handle tag_ids
        tag_ids = serializer.validated_data.pop('tag_ids', None)
        if tag_ids:
            tags = Tag.objects.filter(id__in=tag_ids, workspace=workspace)
            serializer.validated_data['tags'] = tags
        
        post = service.create_post(
            title=serializer.validated_data['title'],
            content=serializer.validated_data['content'],
            **{k: v for k, v in serializer.validated_data.items() if k not in ['title', 'content']}
        )
        serializer.instance = post
    
    def perform_update(self, serializer):
        """Update post using service"""
        workspace = get_workspace(self.request)
        service = PostService(
            workspace=workspace,
            user=self.request.user
        )
        
        # Handle tag_ids
        tag_ids = serializer.validated_data.pop('tag_ids', None)
        if tag_ids is not None:
            tags = Tag.objects.filter(id__in=tag_ids, workspace=workspace)
            serializer.validated_data['tags'] = tags
        
        post = service.update_post(
            serializer.instance,
            **serializer.validated_data
        )
        serializer.instance = post
    
    @action(detail=True, methods=['post'])
    def publish(self, request, slug=None):
        """Publish post immediately"""
        post = self.get_object()
        workspace = get_workspace(request)
        service = PostService(
            workspace=workspace,
            user=request.user
        )
        post = service.publish_post(post)
        serializer = self.get_serializer(post)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def schedule(self, request, slug=None):
        """Schedule post for future publishing"""
        post = self.get_object()
        publish_at = request.data.get('publish_at')
        
        if not publish_at:
            return Response(
                {'detail': 'publish_at is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        workspace = get_workspace(request)
        service = PostService(
            workspace=workspace,
            user=request.user
        )
        post = service.schedule_post(post, publish_at)
        serializer = self.get_serializer(post)
        return Response(serializer.data)


class MediaViewSet(viewsets.ModelViewSet):
    """
    Media library ViewSet
    
    Staff can upload and manage media files
    """
    serializer_class = MediaSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """Get media files for current workspace"""
        workspace = get_workspace(self.request)
        queryset = Media.objects.filter(
            workspace=workspace
        ).select_related('uploaded_by')
        
        # Filter by type if provided
        file_type = self.request.query_params.get('type')
        if file_type:
            queryset = queryset.filter(file_type=file_type)
        
        return queryset.order_by('-uploaded_at')
    
    def perform_create(self, serializer):
        """Upload media using service"""
        workspace = get_workspace(self.request)
        service = MediaService(
            workspace=workspace,
            user=self.request.user
        )
        
        file = self.request.FILES.get('file')
        if not file:
            from bfg.core.exceptions import ValidationError
            raise ValidationError('File is required')
        
        media = service.upload_media(
            file=file,
            title=self.request.data.get('title', ''),
            alt_text=self.request.data.get('alt_text', ''),
            caption=self.request.data.get('caption', ''),
        )
        serializer.instance = media
    
    def perform_destroy(self, instance):
        """Delete media using service"""
        workspace = get_workspace(self.request)
        service = MediaService(
            workspace=workspace,
            user=self.request.user
        )
        service.delete_media(instance)


class CategoryViewSet(viewsets.ModelViewSet):
    """Category management ViewSet"""
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get categories for current workspace"""
        workspace = get_workspace(self.request)
        language = self.request.query_params.get('lang', 'en')
        content_type = self.request.query_params.get('content_type', '')
        
        queryset = Category.objects.filter(
            workspace=workspace,
            language=language
        ).select_related('parent')
        
        # Filter by content type if provided
        if content_type:
            queryset = queryset.filter(
                Q(content_type_name='') | Q(content_type_name=content_type)
            )
        
        # Filter active by default only for list actions
        # For retrieve/update/delete, show all to allow management of inactive categories
        if self.action == 'list':
            show_all = self.request.query_params.get('show_all', 'false').lower() == 'true'
            if not show_all:
                queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('order', 'name')
    
    def perform_create(self, serializer):
        """Set workspace on create"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)
    
    @action(detail=False, methods=['get'])
    def templates(self, request):
        """Get available category templates"""
        from bfg.web.category_templates import get_all_templates
        return Response(get_all_templates())
    
    @action(detail=False, methods=['post'], url_path='from-template')
    def from_template(self, request):
        """Create category from template"""
        from bfg.web.category_templates import get_template
        from django.utils.text import slugify
        
        workspace = get_workspace(request)
        template_key = request.data.get('template')
        name = request.data.get('name')
        slug = request.data.get('slug')
        language = request.data.get('language', 'en')
        
        if not template_key:
            return Response(
                {'error': 'Template key is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        template = get_template(template_key)
        if not template:
            return Response(
                {'error': f"Template '{template_key}' not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Use template defaults if not provided
        final_name = name or template.get('name_zh' if language == 'zh' else 'name', template_key)
        final_slug = slug or slugify(final_name or template_key)
        
        # Check for existing slug
        if Category.objects.filter(workspace=workspace, slug=final_slug, language=language).exists():
            return Response(
                {'error': f"Category with slug '{final_slug}' already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        category = Category.objects.create(
            workspace=workspace,
            name=final_name,
            slug=final_slug,
            description=template.get('description_zh' if language == 'zh' else 'description', ''),
            content_type_name=template['content_type_name'],
            icon=template.get('icon', ''),
            fields_schema=template.get('fields_schema', {}),
            language=language,
        )
        
        serializer = CategorySerializer(category)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TagViewSet(viewsets.ModelViewSet):
    """Tag management ViewSet"""
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get tags for current workspace"""
        workspace = get_workspace(self.request)
        language = self.request.query_params.get('lang', 'en')
        return Tag.objects.filter(
            workspace=workspace,
            language=language
        ).order_by('name')


class ThemeViewSet(viewsets.ModelViewSet):
    """Theme management ViewSet"""
    serializer_class = ThemeSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """Get themes for current workspace"""
        workspace = get_workspace(self.request)
        queryset = Theme.objects.filter(workspace=workspace)
        
        # Filter active by default, but allow showing all for management
        show_all = self.request.query_params.get('show_all', 'false').lower() == 'true'
        if not show_all:
            queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('name')
    
    def perform_create(self, serializer):
        """Set workspace on create"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)


class LanguageViewSet(viewsets.ModelViewSet):
    """Language management ViewSet"""
    serializer_class = LanguageSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get languages for current workspace"""
        workspace = get_workspace(self.request)
        queryset = Language.objects.filter(workspace=workspace)
        
        # Filter active by default, but allow showing all for management
        show_all = self.request.query_params.get('show_all', 'false').lower() == 'true'
        if not show_all:
            queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('order', 'name')
    
    def perform_create(self, serializer):
        """Set workspace on create"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set language as default"""
        workspace = get_workspace(request)
        language = self.get_object()
        
        # Unset other default languages
        Language.objects.filter(workspace=workspace, is_default=True).update(is_default=False)
        
        # Set this as default
        language.is_default = True
        language.save()
        
        return Response({'status': 'default language set'})


class MenuViewSet(viewsets.ModelViewSet):
    """Menu management ViewSet"""
    serializer_class = MenuSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        """Get menus for current workspace. Filter by language only when lang query param is set (for admin list, show all languages)."""
        workspace = get_workspace(self.request)
        language = self.request.query_params.get('lang', '')
        location = self.request.query_params.get('location', '')
        
        queryset = Menu.objects.filter(workspace=workspace).prefetch_related('items')
        if language:
            queryset = queryset.filter(language=language)
        if location:
            queryset = queryset.filter(location=location)
        
        # Filter active by default, but allow showing all for management
        show_all = self.request.query_params.get('show_all', 'false').lower() == 'true'
        if not show_all:
            queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('name')
    
    def perform_create(self, serializer):
        """Set workspace on create"""
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)


class InquiryViewSet(viewsets.ModelViewSet):
    """
    Inquiry management ViewSet
    
    Public can create inquiries, staff can view and manage
    """
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action == 'create':
            return InquiryCreateSerializer
        if self.action == 'retrieve':
            return InquiryDetailSerializer
        return InquiryListSerializer
    
    def get_permissions(self):
        """Set permissions based on action"""
        if self.action == 'create':
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceStaff()]
    
    def get_queryset(self):
        """Get inquiries for current workspace"""
        workspace = get_workspace(self.request)
        
        queryset = Inquiry.objects.filter(
            workspace=workspace
        ).select_related('site', 'source_page', 'assigned_to')
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by type
        inquiry_type = self.request.query_params.get('type')
        if inquiry_type:
            queryset = queryset.filter(inquiry_type=inquiry_type)
        
        # Filter by assigned user
        assigned_to = self.request.query_params.get('assigned_to')
        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create inquiry using service"""
        workspace = get_workspace(self.request)
        service = InquiryService(
            workspace=workspace,
            user=self.request.user if self.request.user.is_authenticated else None
        )
        
        # Get client info
        ip_address = self.request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        if not ip_address:
            ip_address = self.request.META.get('REMOTE_ADDR')
        
        user_agent = self.request.META.get('HTTP_USER_AGENT', '')
        
        # Get site from domain if available
        site = None
        host = self.request.META.get('HTTP_HOST', '')
        if host:
            site = Site.objects.filter(domain=host, workspace=workspace).first()
        
        inquiry = service.create_inquiry(
            name=serializer.validated_data['name'],
            message=serializer.validated_data['message'],
            inquiry_type=serializer.validated_data.get('inquiry_type', 'inquiry'),
            site=site,
            email=serializer.validated_data.get('email', ''),
            phone=serializer.validated_data.get('phone', ''),
            subject=serializer.validated_data.get('subject', ''),
            form_data=serializer.validated_data.get('form_data', {}),
            source_url=serializer.validated_data.get('source_url', ''),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        serializer.instance = inquiry
    
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """Assign inquiry to user"""
        inquiry = self.get_object()
        workspace = get_workspace(request)
        service = InquiryService(workspace=workspace, user=request.user)
        
        user_id = request.data.get('user_id')
        inquiry = service.assign_inquiry(inquiry, user_id)
        serializer = InquiryDetailSerializer(inquiry)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update inquiry status"""
        inquiry = self.get_object()
        workspace = get_workspace(request)
        service = InquiryService(workspace=workspace, user=request.user)
        
        new_status = request.data.get('status')
        notes = request.data.get('notes')
        
        if not new_status:
            return Response(
                {'error': 'Status is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        inquiry = service.update_inquiry_status(inquiry, new_status, notes)
        serializer = InquiryDetailSerializer(inquiry)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get inquiry statistics"""
        workspace = get_workspace(request)
        service = InquiryService(workspace=workspace, user=request.user)
        return Response(service.get_inquiry_stats())


class BookingTimeSlotViewSet(viewsets.ModelViewSet):
    """
    Booking time slot management.

    Staff can manage all time slots; public can view available slots via the `available` action.
    """

    serializer_class = BookingTimeSlotSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        qs = BookingTimeSlot.objects.filter(workspace=workspace).select_related('site')

        slot_type = self.request.query_params.get('type')
        if slot_type:
            qs = qs.filter(slot_type=slot_type)

        date = self.request.query_params.get('date')
        if date:
            qs = qs.filter(date=date)

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            if str(is_active).lower() in ['true', '1', 'yes']:
                qs = qs.filter(is_active=True)
            elif str(is_active).lower() in ['false', '0', 'no']:
                qs = qs.filter(is_active=False)

        return qs.order_by('date', 'start_time')

    def perform_create(self, serializer):
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def available(self, request):
        """
        Public endpoint to fetch available booking time slots.

        Note: availability is computed as current_bookings < max_bookings and is_active=True.
        """
        workspace = get_workspace(request)
        qs = BookingTimeSlot.objects.filter(
            workspace=workspace,
            is_active=True,
        ).select_related('site')

        slot_type = request.query_params.get('type')
        if slot_type:
            qs = qs.filter(slot_type=slot_type)

        date = request.query_params.get('date')
        if date:
            qs = qs.filter(date=date)

        qs = qs.filter(current_bookings__lt=models.F('max_bookings')).order_by('date', 'start_time')
        serializer = BookingTimeSlotSerializer(qs, many=True)
        return Response(serializer.data)


class BookingViewSet(viewsets.ModelViewSet):
    """
    Booking management.

    - create: public (guest) or authenticated user
    - list/retrieve/update: staff only by default
    """

    serializer_class = BookingSerializer

    def get_permissions(self):
        if self.action in ('create', 'my'):
            if self.action == 'my':
                return [IsAuthenticated()]
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceStaff()]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        qs = Booking.objects.filter(workspace=workspace).select_related('timeslot', 'customer')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        slot_type = self.request.query_params.get('type')
        if slot_type:
            qs = qs.filter(timeslot__slot_type=slot_type)

        customer_id = self.request.query_params.get('customer')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        return qs.order_by('-created_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == 'create' and self.request.user.is_authenticated:
            from bfg.common.models import Customer
            workspace = get_workspace(self.request)
            customer = Customer.objects.filter(workspace=workspace, user=self.request.user).first()
            context['resolved_customer'] = customer
        return context

    @action(detail=False, methods=['get'], url_path='my')
    def my(self, request):
        """
        List bookings for the current user (customer) in this workspace.
        Requires authenticated user; filters by customer linked to request.user.
        """
        from bfg.common.models import Customer

        workspace = get_workspace(request)
        customer = Customer.objects.filter(workspace=workspace, user=request.user).first()
        if not customer:
            return Response([], status=status.HTTP_200_OK)

        qs = (
            Booking.objects.filter(workspace=workspace, customer=customer)
            .select_related('timeslot')
            .order_by('-created_at')
        )
        serializer = BookingSerializer(qs, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """
        Create booking and increment timeslot current_bookings safely.
        """
        from django.db import transaction
        workspace = get_workspace(self.request)
        timeslot: BookingTimeSlot = serializer.validated_data['timeslot']

        # Attach customer if authenticated and a Customer exists in this workspace
        customer = None
        if self.request.user.is_authenticated:
            from bfg.common.models import Customer
            customer = Customer.objects.filter(workspace=workspace, user=self.request.user).first()

        with transaction.atomic():
            locked = BookingTimeSlot.objects.select_for_update().get(pk=timeslot.pk)
            if not locked.is_active:
                raise ValidationError("Selected time slot is not active.")
            if locked.current_bookings >= locked.max_bookings:
                raise ValidationError("Selected time slot is fully booked.")

            booking = serializer.save(workspace=workspace, customer=customer or serializer.validated_data.get('customer'))
            locked.current_bookings = models.F('current_bookings') + 1
            locked.save(update_fields=['current_bookings'])

        serializer.instance = booking
        workspace = get_workspace(self.request)
        global_dispatcher.dispatch('booking.created', {
            'workspace': workspace,
            'user': self.request.user if self.request.user.is_authenticated else None,
            'data': {'booking': booking},
        })

    def perform_update(self, serializer):
        """Emit status_changed when status changes; handlers trigger notifications."""
        booking = serializer.instance
        old_status = booking.status
        super().perform_update(serializer)
        booking.refresh_from_db()
        new_status = booking.status
        if old_status == new_status:
            return
        workspace = get_workspace(self.request)
        global_dispatcher.dispatch('booking.status_changed', {
            'workspace': workspace,
            'user': self.request.user if self.request.user.is_authenticated else None,
            'data': {'booking': booking, 'old_status': old_status, 'new_status': new_status},
        })

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        booking = self.get_object()
        old_status = booking.status
        booking.status = 'confirmed'
        booking.save(update_fields=['status', 'updated_at'])
        workspace = get_workspace(request)
        global_dispatcher.dispatch('booking.status_changed', {
            'workspace': workspace,
            'user': request.user if request.user.is_authenticated else None,
            'data': {'booking': booking, 'old_status': old_status, 'new_status': 'confirmed'},
        })
        return Response(BookingSerializer(booking).data)

    @action(detail=True, methods=['post'], url_path='cancel', permission_classes=[AllowAny])
    def cancel(self, request, pk=None):
        """
        Cancel a booking.

        Staff can cancel any booking. For public cancel, caller must provide email or phone that matches booking.
        """
        booking = self.get_object()

        if request.user.is_authenticated and getattr(request, 'is_staff_member', False):
            pass  # Staff can cancel any booking
        elif request.user.is_authenticated:
            from bfg.common.models import Customer
            workspace = get_workspace(request)
            customer = Customer.objects.filter(workspace=workspace, user=request.user).first()
            if customer and booking.customer_id == customer.id:
                pass  # Own booking (same as "my" list)
            else:
                return Response({'error': 'Invalid credentials for cancelling this booking.'}, status=status.HTTP_403_FORBIDDEN)
        else:
            email = (request.data.get('email') or '').strip().lower()
            phone = (request.data.get('phone') or '').strip()
            if email and booking.email and booking.email.strip().lower() == email:
                pass
            elif phone and booking.phone and booking.phone.strip() == phone:
                pass
            else:
                return Response({'error': 'Invalid credentials for cancelling this booking.'}, status=status.HTTP_403_FORBIDDEN)

        if booking.status in ['cancelled', 'completed']:
            return Response(BookingSerializer(booking).data)

        old_status = booking.status
        from django.db import transaction
        with transaction.atomic():
            # Decrement slot count if it was not already cancelled
            slot = BookingTimeSlot.objects.select_for_update().get(pk=booking.timeslot_id)
            if slot.current_bookings > 0:
                slot.current_bookings = models.F('current_bookings') - 1
                slot.save(update_fields=['current_bookings'])

            booking.status = 'cancelled'
            booking.save(update_fields=['status', 'updated_at'])

        workspace = get_workspace(request)
        global_dispatcher.dispatch('booking.status_changed', {
            'workspace': workspace,
            'user': request.user if request.user.is_authenticated else None,
            'data': {'booking': booking, 'old_status': old_status, 'new_status': 'cancelled'},
        })
        return Response(BookingSerializer(booking).data)


class BlockTypesView(APIView):
    """Get available block types for page builder"""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get(self, request):
        """Get list of available block types with schemas"""
        workspace = get_workspace(request)
        service = BlockService(workspace=workspace, user=request.user)
        return Response(service.get_available_block_types())


class BlockValidateView(APIView):
    """Validate block configuration"""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def post(self, request):
        """Validate blocks configuration"""
        workspace = get_workspace(request)
        service = BlockService(workspace=workspace, user=request.user)
        
        blocks = request.data.get('blocks', [])
        validation = service.validate_blocks(blocks)
        return Response(validation)


# --- Newsletter ---


class NewsletterSubscriptionViewSet(viewsets.ModelViewSet):
    """Newsletter subscriptions. Public create; staff list/retrieve/update/destroy/unsubscribe."""
    def get_serializer_class(self):
        if self.action == 'create':
            return NewsletterSubscriptionCreateSerializer
        if self.action in ('retrieve', 'unsubscribe'):
            return NewsletterSubscriptionDetailSerializer
        if self.action in ('update', 'partial_update'):
            return NewsletterSubscriptionUpdateSerializer
        return NewsletterSubscriptionListSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceStaff()]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        qs = NewsletterSubscription.objects.filter(workspace=workspace).order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        workspace = get_workspace(self.request)
        ip_address = self.request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or self.request.META.get('REMOTE_ADDR')
        user_agent = self.request.META.get('HTTP_USER_AGENT', '')
        site = None
        host = self.request.META.get('HTTP_HOST', '')
        if host:
            site = Site.objects.filter(domain=host, workspace=workspace).first()
        service = NewsletterService(workspace=workspace, user=None)
        sub = service.subscribe(
            email=serializer.validated_data['email'],
            site=site,
            source_url=serializer.validated_data.get('source_url', ''),
            ip_address=ip_address,
            user_agent=user_agent or '',
        )
        serializer.instance = sub

    @action(detail=True, methods=['post'])
    def unsubscribe(self, request, pk=None):
        """Mark subscription as unsubscribed."""
        workspace = get_workspace(request)
        service = NewsletterService(workspace=workspace, user=request.user)
        sub = self.get_object()
        updated = service.unsubscribe(subscription_id=sub.id)
        return Response(NewsletterSubscriptionDetailSerializer(updated).data if updated else {})


class NewsletterUnsubscribeByTokenView(APIView):
    """Public unsubscribe by token (e.g. link in email). Token is unique, so workspace is resolved from subscription."""
    permission_classes = [AllowAny]

    def _unsubscribe(self, token):
        if not token:
            return None, Response({'detail': 'Missing token.'}, status=status.HTTP_400_BAD_REQUEST)
        sub = NewsletterSubscription.objects.filter(unsubscribe_token=token).first()
        if not sub:
            return None, Response({'detail': 'Subscription not found or already unsubscribed.'}, status=status.HTTP_404_NOT_FOUND)
        service = NewsletterService(workspace=sub.workspace, user=None)
        service.unsubscribe(token=token)
        sub.refresh_from_db()
        return sub, Response({'detail': 'Unsubscribed.', 'email': sub.email})

    def get(self, request):
        token = request.query_params.get('token')
        sub, resp = self._unsubscribe(token)
        return resp

    def post(self, request):
        token = request.data.get('token') or request.query_params.get('token')
        sub, resp = self._unsubscribe(token)
        return resp


class NewsletterTemplateViewSet(viewsets.ModelViewSet):
    """Newsletter templates CRUD (staff only)."""
    serializer_class = NewsletterTemplateSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        return NewsletterTemplate.objects.filter(workspace=workspace).order_by('name')

    def perform_create(self, serializer):
        workspace = get_workspace(self.request)
        serializer.save(workspace=workspace)


class NewsletterSendViewSet(viewsets.ModelViewSet):
    """Newsletter send jobs. CRUD + schedule + send_now."""
    serializer_class = NewsletterSendSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        qs = NewsletterSend.objects.filter(workspace=workspace).select_related('template', 'created_by').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        workspace = get_workspace(self.request)
        template = serializer.validated_data.get('template')
        subject = serializer.validated_data.get('subject', '')
        content = serializer.validated_data.get('content', '')
        if template and (not subject or not content):
            subject = subject or template.subject_template
            content = content or template.body_html
        serializer.save(
            workspace=workspace,
            created_by=self.request.user,
            template=template,
            subject=subject,
            content=content,
        )

    @action(detail=True, methods=['post'], url_path='schedule')
    def schedule(self, request, pk=None):
        """Set scheduled_at and status=scheduled."""
        from django.utils.dateparse import parse_datetime
        send = self.get_object()
        scheduled_at = request.data.get('scheduled_at')
        if not scheduled_at:
            return Response({'detail': 'scheduled_at required.'}, status=status.HTTP_400_BAD_REQUEST)
        dt = parse_datetime(scheduled_at) if isinstance(scheduled_at, str) else scheduled_at
        if not dt:
            return Response({'detail': 'Invalid scheduled_at.'}, status=status.HTTP_400_BAD_REQUEST)
        workspace = get_workspace(request)
        service = NewsletterService(workspace=workspace, user=request.user)
        service.schedule_send(send, dt)
        return Response(NewsletterSendSerializer(send).data)

    @action(detail=True, methods=['post'], url_path='send-now')
    def send_now(self, request, pk=None):
        """Trigger immediate send (sync or async)."""
        send = self.get_object()
        if send.status not in ('draft', 'scheduled'):
            return Response({'detail': 'Send already completed or cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        workspace = get_workspace(request)
        service = NewsletterService(workspace=workspace, user=request.user)
        service.execute_send(send)
        return Response(NewsletterSendSerializer(send).data)


class NewsletterSendLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Newsletter send logs (read-only, filter by newsletter_send or subscription)."""
    serializer_class = NewsletterSendLogSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get_queryset(self):
        workspace = get_workspace(self.request)
        qs = NewsletterSendLog.objects.filter(workspace=workspace).select_related('newsletter_send', 'subscription').order_by('-sent_at')
        send_id = self.request.query_params.get('newsletter_send_id')
        if send_id:
            qs = qs.filter(newsletter_send_id=send_id)
        sub_id = self.request.query_params.get('subscription_id')
        if sub_id:
            qs = qs.filter(subscription_id=sub_id)
        return qs

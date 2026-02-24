"""
BFG Web Module Serializers

Serializers for web module models
"""

from rest_framework import serializers
from bfg.web.models import (
    Site, Theme, Language, Page, Post, Category, Tag, Menu, MenuItem, Media, Inquiry,
    BookingTimeSlot, Booking,
    NewsletterSubscription, NewsletterTemplate, NewsletterSend, NewsletterSendLog,
)


class SiteSerializer(serializers.ModelSerializer):
    """Site serializer"""
    
    class Meta:
        model = Site
        fields = [
            'id', 'workspace', 'name', 'domain', 'theme', 'default_language', 'languages',
            'site_title', 'site_description', 'notification_config', 'is_active', 'is_default',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'workspace', 'created_at', 'updated_at']


class ThemeSerializer(serializers.ModelSerializer):
    """Theme serializer"""
    
    class Meta:
        model = Theme
        fields = [
            'id', 'workspace', 'name', 'code', 'description', 'template_path',
            'logo', 'favicon', 'primary_color', 'secondary_color',
            'homepage_title', 'homepage_subtitle', 'homepage_text', 'homepage_image',
            'custom_css', 'custom_js', 'config', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class LanguageSerializer(serializers.ModelSerializer):
    """Language serializer"""
    
    class Meta:
        model = Language
        fields = [
            'id', 'workspace', 'code', 'name', 'native_name',
            'is_default', 'is_active', 'order', 'is_rtl'
        ]
        read_only_fields = ['id']


class PageListSerializer(serializers.ModelSerializer):
    """Page list serializer (concise)"""
    has_blocks = serializers.SerializerMethodField()
    
    class Meta:
        model = Page
        fields = [
            'id', 'title', 'slug', 'content', 'status', 'is_featured',
            'language', 'order', 'published_at', 'updated_at', 'has_blocks'
        ]
        read_only_fields = ['id', 'published_at', 'updated_at', 'has_blocks']
    
    def get_has_blocks(self, obj):
        """Check if page has block configuration"""
        return bool(obj.blocks)


class PageDetailSerializer(serializers.ModelSerializer):
    """Page detail serializer (full)"""
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    parent_title = serializers.CharField(source='parent.title', read_only=True, allow_null=True)
    
    class Meta:
        model = Page
        fields = [
            'id', 'title', 'slug', 'content', 'excerpt', 'blocks', 'parent', 'parent_title',
            'template', 'meta_title', 'meta_description', 'meta_keywords',
            'status', 'published_at', 'is_featured', 'allow_comments',
            'order', 'language', 'created_at', 'updated_at',
            'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'published_at']


class PageRenderedSerializer(serializers.ModelSerializer):
    """Page serializer for public rendering with resolved blocks"""
    blocks = serializers.JSONField()  # Will contain resolved data
    
    class Meta:
        model = Page
        fields = [
            'id', 'title', 'slug', 'excerpt', 'blocks',
            'meta_title', 'meta_description', 'meta_keywords',
            'language', 'published_at'
        ]


class CategorySerializer(serializers.ModelSerializer):
    """Category serializer"""
    parent_name = serializers.CharField(source='parent.name', read_only=True, allow_null=True)
    fields_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'slug', 'description', 'parent', 'parent_name',
            'content_type_name', 'fields_schema', 'fields_count',
            'icon', 'color', 'order', 'is_active', 'language'
        ]
        read_only_fields = ['id', 'fields_count']
    
    def get_fields_count(self, obj):
        """Get count of custom fields defined"""
        return len(obj.fields_schema) if obj.fields_schema else 0


class TagSerializer(serializers.ModelSerializer):
    """Tag serializer"""
    
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug', 'language']
        read_only_fields = ['id']


class PostListSerializer(serializers.ModelSerializer):
    """Post list serializer (concise)"""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)
    
    class Meta:
        model = Post
        fields = [
            'id', 'title', 'slug', 'excerpt', 'featured_image',
            'category', 'category_name', 'custom_fields', 'status', 'published_at',
            'view_count', 'comment_count', 'language',
            'author', 'author_name', 'updated_at'
        ]
        read_only_fields = ['id', 'view_count', 'comment_count', 'published_at', 'updated_at']


class PostDetailSerializer(serializers.ModelSerializer):
    """Post detail serializer (full)"""
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    category_fields_schema = serializers.JSONField(source='category.fields_schema', read_only=True)
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Post
        fields = [
            'id', 'title', 'slug', 'content', 'excerpt', 'featured_image',
            'category', 'category_name', 'category_fields_schema', 'custom_fields',
            'tags', 'tag_ids',
            'meta_title', 'meta_description', 'status', 'published_at',
            'view_count', 'comment_count', 'allow_comments', 'language',
            'created_at', 'updated_at', 'author', 'author_name'
        ]
        read_only_fields = ['id', 'view_count', 'comment_count', 'created_at', 'updated_at', 'author', 'published_at', 'category_fields_schema']


class MenuItemSerializer(serializers.ModelSerializer):
    """Menu item serializer (read, with nested children)"""
    children = serializers.SerializerMethodField()
    
    class Meta:
        model = MenuItem
        fields = [
            'id', 'title', 'url', 'page', 'post', 'parent',
            'icon', 'css_class', 'order', 'open_in_new_tab',
            'is_active', 'children'
        ]
        read_only_fields = ['id']
    
    def get_children(self, obj):
        """Get nested children"""
        children = obj.children.filter(is_active=True).order_by('order')
        return MenuItemSerializer(children, many=True).data


class MenuItemWriteSerializer(serializers.ModelSerializer):
    """Menu item serializer for create/update (flat, no children)."""
    
    class Meta:
        model = MenuItem
        fields = ['id', 'title', 'url', 'order', 'open_in_new_tab', 'is_active']
        read_only_fields = ['id']


class MenuSerializer(serializers.ModelSerializer):
    """Menu serializer with nested items. Accepts items on create/update."""
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        allow_empty=True
    )
    items_read = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Menu
        fields = ['id', 'name', 'slug', 'location', 'language', 'is_active', 'items', 'items_read']
        read_only_fields = ['id']
    
    def get_items_read(self, obj):
        """Nested items for response (same key as request uses 'items' for write)."""
        items = obj.items.filter(parent__isnull=True).order_by('order')
        return MenuItemSerializer(items, many=True).data
    
    def to_representation(self, instance):
        """Expose items_read as 'items' in response."""
        data = super().to_representation(instance)
        data['items'] = data.pop('items_read', [])
        return data
    
    def create(self, validated_data):
        items_data = validated_data.pop('items', []) or []
        menu = Menu.objects.create(**validated_data)
        self._sync_items(menu, items_data)
        return menu
    
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if items_data is not None:
            self._sync_items(instance, items_data)
        return instance
    
    def _sync_items(self, menu, items_data):
        """Replace top-level menu items with the given list (flat)."""
        ids_seen = set()
        for i, raw in enumerate(items_data):
            item_id = raw.get('id') if isinstance(raw.get('id'), int) else None
            order = raw.get('order', i)
            title = raw.get('title', '').strip()
            url = raw.get('url', '').strip()
            if not title and not url:
                continue
            open_in_new_tab = raw.get('open_in_new_tab', False)
            is_active = raw.get('is_active', True)
            if item_id:
                MenuItem.objects.filter(menu=menu, id=item_id).update(
                    title=title, url=url or '/', order=order,
                    open_in_new_tab=open_in_new_tab, is_active=is_active
                )
                ids_seen.add(item_id)
            else:
                item = MenuItem.objects.create(
                    menu=menu, title=title, url=url or '/', order=order,
                    open_in_new_tab=open_in_new_tab, is_active=is_active
                )
                ids_seen.add(item.id)
        MenuItem.objects.filter(menu=menu, parent__isnull=True).exclude(id__in=ids_seen).delete()


class MediaSerializer(serializers.ModelSerializer):
    """Media serializer"""
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Media
        fields = [
            'id', 'file', 'file_url', 'file_name', 'file_type', 'mime_type',
            'file_size', 'title', 'alt_text', 'caption',
            'width', 'height', 'uploaded_by', 'uploaded_by_name', 'uploaded_at'
        ]
        read_only_fields = ['id', 'file_name', 'file_type', 'mime_type', 'file_size', 'width', 'height', 'uploaded_by', 'uploaded_at']
    
    def get_file_url(self, obj):
        """Get full file URL"""
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None


class InquiryListSerializer(serializers.ModelSerializer):
    """Inquiry list serializer (concise)"""
    type_display = serializers.CharField(source='get_inquiry_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True, allow_null=True)
    
    class Meta:
        model = Inquiry
        fields = [
            'id', 'inquiry_type', 'type_display', 'status', 'status_display',
            'name', 'email', 'phone', 'subject',
            'assigned_to', 'assigned_to_name',
            'notification_sent', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'type_display', 'status_display', 'assigned_to_name', 'created_at', 'updated_at']


class InquiryDetailSerializer(serializers.ModelSerializer):
    """Inquiry detail serializer (full)"""
    type_display = serializers.CharField(source='get_inquiry_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True, allow_null=True)
    source_page_title = serializers.CharField(source='source_page.title', read_only=True, allow_null=True)
    
    class Meta:
        model = Inquiry
        fields = [
            'id', 'site', 'inquiry_type', 'type_display', 'status', 'status_display',
            'name', 'email', 'phone', 'subject', 'message', 'form_data',
            'source_page', 'source_page_title', 'source_url', 'ip_address', 'user_agent',
            'assigned_to', 'assigned_to_name', 'notes',
            'notification_sent', 'notification_sent_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'type_display', 'status_display', 'assigned_to_name', 'source_page_title',
            'ip_address', 'user_agent', 'notification_sent', 'notification_sent_at',
            'created_at', 'updated_at'
        ]


class InquiryCreateSerializer(serializers.ModelSerializer):
    """Inquiry creation serializer (public submission)"""
    
    class Meta:
        model = Inquiry
        fields = [
            'inquiry_type', 'name', 'email', 'phone', 'subject', 'message', 'form_data',
            'source_url'
        ]
    
    def validate_email(self, value):
        """Validate email is provided for certain inquiry types"""
        inquiry_type = self.initial_data.get('inquiry_type', 'inquiry')
        if inquiry_type in ['booking', 'inquiry'] and not value:
            raise serializers.ValidationError("Email is required for booking and inquiry submissions.")
        return value


class BookingTimeSlotSerializer(serializers.ModelSerializer):
    """Booking time slot serializer"""

    class Meta:
        model = BookingTimeSlot
        fields = [
            'id', 'workspace', 'site', 'slot_type', 'name',
            'date', 'start_time', 'end_time',
            'max_bookings', 'current_bookings',
            'is_active', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'workspace', 'current_bookings', 'created_at', 'updated_at']


class BookingSerializer(serializers.ModelSerializer):
    """Booking serializer"""

    slot_type = serializers.CharField(source='timeslot.slot_type', read_only=True)
    slot_date = serializers.DateField(source='timeslot.date', read_only=True)
    slot_start_time = serializers.TimeField(source='timeslot.start_time', read_only=True)
    slot_end_time = serializers.TimeField(source='timeslot.end_time', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'workspace',
            'timeslot', 'slot_type', 'slot_date', 'slot_start_time', 'slot_end_time',
            'customer',
            'name', 'email', 'phone',
            'status', 'notes', 'admin_notes', 'metadata',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'workspace', 'status', 'admin_notes', 'created_at', 'updated_at']

    def validate(self, attrs):
        """
        If customer is not provided, require guest contact fields.
        When request is authenticated, use resolved_customer from context so guest fields are not required.
        """
        customer = attrs.get('customer')
        if not customer:
            resolved = self.context.get('resolved_customer')
            if resolved is not None:
                attrs['customer'] = resolved
                return attrs
            name = attrs.get('name') or ''
            email = attrs.get('email') or ''
            phone = attrs.get('phone') or ''
            if not name or (not email and not phone):
                raise serializers.ValidationError("Guest booking requires name and (email or phone).")
        return attrs


# --- Newsletter ---


class NewsletterSubscriptionCreateSerializer(serializers.ModelSerializer):
    """Public subscription create (email only)."""
    class Meta:
        model = NewsletterSubscription
        fields = ['email']

    def validate_email(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Email is required.")
        return value.strip().lower()


class NewsletterSubscriptionListSerializer(serializers.ModelSerializer):
    """Subscription list (admin)."""
    class Meta:
        model = NewsletterSubscription
        fields = ['id', 'email', 'status', 'created_at', 'updated_at']


class NewsletterSubscriptionDetailSerializer(serializers.ModelSerializer):
    """Subscription detail including unsubscribe_token."""
    class Meta:
        model = NewsletterSubscription
        fields = [
            'id', 'email', 'status', 'site', 'source_url', 'unsubscribe_token',
            'created_at', 'updated_at',
        ]


class NewsletterSubscriptionUpdateSerializer(serializers.ModelSerializer):
    """Subscription update (admin: email, status)."""
    class Meta:
        model = NewsletterSubscription
        fields = ['email', 'status']


class NewsletterTemplateSerializer(serializers.ModelSerializer):
    """Template CRUD."""
    class Meta:
        model = NewsletterTemplate
        fields = ['id', 'name', 'subject_template', 'body_html', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class NewsletterSendSerializer(serializers.ModelSerializer):
    """Send job CRUD; optional template, scheduled_at."""
    class Meta:
        model = NewsletterSend
        fields = [
            'id', 'subject', 'content', 'template', 'scheduled_at', 'status',
            'sent_at', 'created_at', 'updated_at', 'created_by',
        ]
        read_only_fields = ['id', 'status', 'sent_at', 'created_at', 'updated_at']


class NewsletterSendLogSerializer(serializers.ModelSerializer):
    """Send result record (read-only in API)."""
    email = serializers.EmailField(source='subscription.email', read_only=True)
    newsletter_send_subject = serializers.CharField(source='newsletter_send.subject', read_only=True)

    class Meta:
        model = NewsletterSendLog
        fields = [
            'id', 'newsletter_send', 'newsletter_send_subject', 'subscription', 'email',
            'sent_at', 'status', 'error_message',
        ]
        read_only_fields = fields

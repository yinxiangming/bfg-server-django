# -*- coding: utf-8 -*-
"""
Models for BFG Web module.
Website CMS with multi-site, multi-language, and messaging features.
"""

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings


class Site(models.Model):
    """
    Multi-site configuration.
    Each site can have its own domain, theme, and content.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='sites')
    
    # Identification
    name = models.CharField(_("Name"), max_length=100)
    domain = models.CharField(_("Domain"), max_length=255, unique=True)  # e.g., "example.com"
    
    # Theme
    theme = models.ForeignKey('Theme', on_delete=models.SET_NULL, null=True, blank=True, related_name='sites')
    
    # Configuration
    default_language = models.CharField(_("Default Language"), max_length=10, default='en')
    languages = models.JSONField(_("Enabled Languages"), default=list)  # ['en', 'zh-hans']
    
    # SEO
    site_title = models.CharField(_("Site Title"), max_length=255)
    site_description = models.TextField(_("Site Description"), blank=True)
    
    # Notification settings for inquiries
    notification_config = models.JSONField(
        _("Notification Config"),
        default=dict,
        blank=True,
        help_text=_("Email and webhook settings for inquiry notifications")
    )
    # Example structure:
    # {
    #     "email": {
    #         "enabled": true,
    #         "recipients": ["admin@example.com"],
    #         "template": "default"
    #     },
    #     "webhook": {
    #         "enabled": false,
    #         "url": "https://hooks.example.com/inquiry",
    #         "secret": "..."
    #     }
    # }
    
    # Settings
    is_active = models.BooleanField(_("Active"), default=True)
    is_default = models.BooleanField(_("Default Site"), default=False)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Site")
        verbose_name_plural = _("Sites")
        ordering = ['name']
        indexes = [
            models.Index(fields=['domain']),
            models.Index(fields=['workspace', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.domain})"


class Theme(models.Model):
    """
    Theme template with customization options.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='themes', null=True, blank=True, default=None)
    
    # Basic Info
    name = models.CharField(_("Name"), max_length=100)
    code = models.CharField(_("Code"), max_length=50)  # Internal code
    description = models.TextField(_("Description"), blank=True)
    
    # Template
    template_path = models.CharField(_("Template Path"), max_length=255)  # Path to template directory
    
    # Customization
    logo = models.ImageField(_("Logo"), upload_to='themes/logos/', blank=True)
    favicon = models.ImageField(_("Favicon"), upload_to='themes/favicons/', blank=True)
    
    # Colors
    primary_color = models.CharField(_("Primary Color"), max_length=20, default='#007bff')
    secondary_color = models.CharField(_("Secondary Color"), max_length=20, default='#6c757d')
    
    # Homepage customization
    homepage_title = models.CharField(_("Homepage Title"), max_length=255, blank=True)
    homepage_subtitle = models.CharField(_("Homepage Subtitle"), max_length=255, blank=True)
    homepage_text = models.TextField(_("Homepage Text"), blank=True)
    homepage_image = models.ImageField(_("Homepage Image"), upload_to='themes/homepage/', blank=True)
    
    # Custom CSS/JS
    custom_css = models.TextField(_("Custom CSS"), blank=True)
    custom_js = models.TextField(_("Custom JavaScript"), blank=True)
    
    # Settings
    config = models.JSONField(_("Configuration"), default=dict, blank=True)  # Additional theme settings
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Theme")
        verbose_name_plural = _("Themes")
        ordering = ['name']
        unique_together = ('workspace', 'code')
    
    def __str__(self):
        return self.name


    def __str__(self):
        return self.name


class Page(models.Model):
    """
    Content page with multi-language support and versioning.
    """
    STATUS_CHOICES = (
        ('draft', _('Draft')),
        ('published', _('Published')),
        ('archived', _('Archived')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='pages')
    
    # Basic Info
    title = models.CharField(_("Title"), max_length=255)
    slug = models.SlugField(_("Slug"), max_length=255)
    
    # Content
    content = models.TextField(_("Content"))  # Rich text content (legacy/fallback)
    excerpt = models.TextField(_("Excerpt"), blank=True)  # Short summary
    
    # Page Builder blocks configuration
    blocks = models.JSONField(
        _("Blocks"),
        default=list,
        blank=True,
        help_text=_("Page builder block configurations")
    )
    # Example structure:
    # [
    #     {
    #         "id": "block_1",
    #         "type": "hero_carousel_v1",
    #         "settings": {"autoPlay": true, "interval": 5000},
    #         "data": {"slides": [{"image": "...", "title": {"en": "...", "zh": "..."}}]}
    #     },
    #     ...
    # ]
    
    # Organization
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    template = models.CharField(_("Template"), max_length=100, default='default')
    
    # SEO
    meta_title = models.CharField(_("Meta Title"), max_length=255, blank=True)
    meta_description = models.TextField(_("Meta Description"), blank=True)
    meta_keywords = models.CharField(_("Meta Keywords"), max_length=255, blank=True)
    
    # Publishing
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='draft')
    published_at = models.DateTimeField(_("Published At"), null=True, blank=True)
    
    # Settings
    is_featured = models.BooleanField(_("Featured"), default=False)
    allow_comments = models.BooleanField(_("Allow Comments"), default=False)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pages_created')
    
    class Meta:
        verbose_name = _("Page")
        verbose_name_plural = _("Pages")
        ordering = ['order', 'title']
        unique_together = ('workspace', 'slug', 'language')
        indexes = [
            models.Index(fields=['workspace', 'slug']),
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['workspace', 'language']),
        ]
    
    def __str__(self):
        return self.title


class Post(models.Model):
    """
    Blog post or news article.
    """
    STATUS_CHOICES = (
        ('draft', _('Draft')),
        ('published', _('Published')),
        ('archived', _('Archived')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='posts')
    
    # Basic Info
    title = models.CharField(_("Title"), max_length=255)
    slug = models.SlugField(_("Slug"), max_length=255)
    
    # Content
    content = models.TextField(_("Content"))
    excerpt = models.TextField(_("Excerpt"), blank=True)
    featured_image = models.ImageField(_("Featured Image"), upload_to='posts/', blank=True)
    
    # Organization
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, related_name='posts')
    tags = models.ManyToManyField('Tag', blank=True, related_name='posts')
    
    # Custom fields based on category's fields_schema
    custom_fields = models.JSONField(
        _("Custom Fields"),
        default=dict,
        blank=True,
        help_text=_("Custom field values defined by the category's fields_schema")
    )
    # Example structure:
    # {
    #     "client_name": "Acme Corp",
    #     "industry": "manufacturing",
    #     "project_duration": "3 months"
    # }
    
    # SEO
    meta_title = models.CharField(_("Meta Title"), max_length=255, blank=True)
    meta_description = models.TextField(_("Meta Description"), blank=True)
    
    # Publishing
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='draft')
    published_at = models.DateTimeField(_("Published At"), null=True, blank=True)
    
    # Engagement
    view_count = models.IntegerField(_("View Count"), default=0)
    comment_count = models.IntegerField(_("Comment Count"), default=0)
    allow_comments = models.BooleanField(_("Allow Comments"), default=True)
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='posts_authored')
    
    class Meta:
        verbose_name = _("Post")
        verbose_name_plural = _("Posts")
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['workspace', 'slug', 'language']),
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['workspace', 'category']),
            models.Index(fields=['-published_at']),
        ]
    
    def __str__(self):
        return self.title


class Category(models.Model):
    """
    Content category with hierarchy support.
    Can be associated with specific content types (post, project, service, faq) or be generic.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='categories')
    
    name = models.CharField(_("Name"), max_length=100)
    slug = models.SlugField(_("Slug"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    
    # Hierarchy
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    
    # Content type filtering (optional)
    content_type_name = models.CharField(
        _("Content Type"),
        max_length=50,
        blank=True,
        help_text=_("Optional: Limit this category to specific content type (post/project/service/faq). Empty for generic categories.")
    )
    
    # Custom fields schema for posts in this category
    fields_schema = models.JSONField(
        _("Fields Schema"),
        default=dict,
        blank=True,
        help_text=_("Schema defining custom fields for posts in this category")
    )
    # Example structure:
    # {
    #     "client_name": {"type": "string", "required": true, "description": "Client name"},
    #     "industry": {"type": "select", "options": [...], "description": "Industry"},
    #     "project_duration": {"type": "string", "description": "Project duration"}
    # }
    
    # Display
    icon = models.CharField(_("Icon"), max_length=50, blank=True)  # Icon class or emoji
    color = models.CharField(_("Color"), max_length=7, blank=True)  # Hex color
    
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    class Meta:
        verbose_name = _("Category")
        verbose_name_plural = _("Categories")
        ordering = ['order', 'name']
        unique_together = ('workspace', 'slug', 'language')
        indexes = [
            models.Index(fields=['workspace', 'parent']),
            models.Index(fields=['workspace', 'content_type_name']),
        ]
    
    def __str__(self):
        return self.name


class Tag(models.Model):
    """
    Content tag for flexible organization.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='tags')
    
    name = models.CharField(_("Name"), max_length=50)
    slug = models.SlugField(_("Slug"), max_length=50)
    
    language = models.CharField(_("Language"), max_length=10)
    
    class Meta:
        verbose_name = _("Tag")
        verbose_name_plural = _("Tags")
        ordering = ['name']
        unique_together = ('workspace', 'slug', 'language')
    
    def __str__(self):
        return self.name


class Menu(models.Model):
    """
    Navigation menu.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='menus')
    
    name = models.CharField(_("Name"), max_length=100)
    slug = models.SlugField(_("Slug"), max_length=100)
    location = models.CharField(_("Location"), max_length=50)  # 'header', 'footer', 'sidebar'
    
    language = models.CharField(_("Language"), max_length=10)
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Menu")
        verbose_name_plural = _("Menus")
        ordering = ['name']
        unique_together = ('workspace', 'slug', 'language')
    
    def __str__(self):
        return f"{self.name} ({self.location})"


class MenuItem(models.Model):
    """
    Individual menu item.
    """
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='items')
    
    title = models.CharField(_("Title"), max_length=100)
    url = models.CharField(_("URL"), max_length=255)  # Can be path or full URL
    
    # Links
    page = models.ForeignKey(Page, null=True, blank=True, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    
    # Display
    icon = models.CharField(_("Icon"), max_length=50, blank=True)
    css_class = models.CharField(_("CSS Class"), max_length=50, blank=True)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    
    # Behavior
    open_in_new_tab = models.BooleanField(_("Open in New Tab"), default=False)
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Menu Item")
        verbose_name_plural = _("Menu Items")
        ordering = ['order', 'title']
    
    def __str__(self):
        return self.title


class Translation(models.Model):
    """
    Generic translation storage for any translatable content.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='translations')
    
    # Generic relation to any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Translation
    field_name = models.CharField(_("Field Name"), max_length=50)
    language = models.CharField(_("Language"), max_length=10)
    value = models.TextField(_("Value"))
    
    class Meta:
        verbose_name = _("Translation")
        verbose_name_plural = _("Translations")
        unique_together = ('content_type', 'object_id', 'field_name', 'language')
    
    def __str__(self):
        return f"{self.field_name} ({self.language})"


class Language(models.Model):
    """
    Supported language configuration.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='languages')
    
    code = models.CharField(_("Code"), max_length=10)  # 'en', 'zh-hans', 'zh-hant'
    name = models.CharField(_("Name"), max_length=100)  # e.g. 'English'
    native_name = models.CharField(_("Native Name"), max_length=100)  # 'English', '简体中文'
    
    is_default = models.BooleanField(_("Default"), default=False)
    is_active = models.BooleanField(_("Active"), default=True)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    
    # RTL support
    is_rtl = models.BooleanField(_("Right-to-Left"), default=False)
    
    class Meta:
        verbose_name = _("Language")
        verbose_name_plural = _("Languages")
        ordering = ['order', 'name']
        unique_together = ('workspace', 'code')
    
    def __str__(self):
        return self.name


class Media(models.Model):
    """
    Media file (image, document, etc.).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='media_files')
    
    # File
    file = models.FileField(_("File"), upload_to='media/%Y/%m/')
    file_name = models.CharField(_("File Name"), max_length=255)
    file_type = models.CharField(_("File Type"), max_length=50)  # 'image', 'document', 'video'
    mime_type = models.CharField(_("MIME Type"), max_length=100)
    file_size = models.BigIntegerField(_("File Size"))  # In bytes
    
    # Metadata
    title = models.CharField(_("Title"), max_length=255, blank=True)
    alt_text = models.CharField(_("Alt Text"), max_length=255, blank=True)
    caption = models.TextField(_("Caption"), blank=True)
    
    # Image-specific
    width = models.IntegerField(_("Width"), null=True, blank=True)
    height = models.IntegerField(_("Height"), null=True, blank=True)
    
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(_("Uploaded At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Media")
        verbose_name_plural = _("Media")
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return self.file_name


class BookingTimeSlot(models.Model):
    """
    Generic booking time slot.

    Designed to be reusable for multiple booking scenarios (drop-off, reservations, services, etc.).
    """

    SLOT_TYPE_CHOICES = (
        ('dropoff', _('Drop-off')),
        ('pickup', _('Pickup')),
        ('appointment', _('Appointment')),
        ('reservation', _('Reservation')),
        ('consultation', _('Consultation')),
    )

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='booking_timeslots')
    site = models.ForeignKey('web.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='booking_timeslots')

    slot_type = models.CharField(_("Slot Type"), max_length=20, choices=SLOT_TYPE_CHOICES, default='appointment')
    name = models.CharField(_("Name"), max_length=100, blank=True)

    date = models.DateField(_("Date"))
    start_time = models.TimeField(_("Start Time"))
    end_time = models.TimeField(_("End Time"))

    max_bookings = models.IntegerField(_("Max Bookings"), default=1)
    current_bookings = models.IntegerField(_("Current Bookings"), default=0)

    is_active = models.BooleanField(_("Active"), default=True)
    notes = models.TextField(_("Notes"), blank=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Booking Time Slot")
        verbose_name_plural = _("Booking Time Slots")
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['workspace', 'slot_type', 'is_active']),
            models.Index(fields=['workspace', 'date']),
        ]

    def __str__(self):
        label = self.name or self.get_slot_type_display()
        return f"{label}: {self.date} {self.start_time}-{self.end_time}"


class Booking(models.Model):
    """
    Generic booking record for a specific time slot.
    """

    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('confirmed', _('Confirmed')),
        ('cancelled', _('Cancelled')),
        ('completed', _('Completed')),
        ('no_show', _('No Show')),
    )

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='bookings')
    timeslot = models.ForeignKey('web.BookingTimeSlot', on_delete=models.PROTECT, related_name='bookings')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, null=True, blank=True, related_name='bookings')

    # Contact info for guest bookings
    name = models.CharField(_("Name"), max_length=100, blank=True)
    email = models.EmailField(_("Email"), blank=True)
    phone = models.CharField(_("Phone"), max_length=50, blank=True)

    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(_("Notes"), blank=True)
    admin_notes = models.TextField(_("Admin Notes"), blank=True)

    metadata = models.JSONField(_("Metadata"), default=dict, blank=True)

    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Booking")
        verbose_name_plural = _("Bookings")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['workspace', '-created_at']),
        ]

    def __str__(self):
        return f"{self.get_status_display()} booking for {self.timeslot_id}"


class Inquiry(models.Model):
    """
    Customer inquiry/submission (booking requests, business inquiries, feedback).
    """
    TYPE_CHOICES = (
        ('booking', _('Booking Request')),
        ('inquiry', _('Business Inquiry')),
        ('feedback', _('Feedback/Complaint')),
        ('other', _('Other')),
    )
    
    STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='inquiries')
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='inquiries')
    
    # Type and status
    inquiry_type = models.CharField(_("Type"), max_length=20, choices=TYPE_CHOICES, default='inquiry')
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Contact info
    name = models.CharField(_("Name"), max_length=100)
    email = models.EmailField(_("Email"), blank=True)
    phone = models.CharField(_("Phone"), max_length=50, blank=True)
    
    # Content
    subject = models.CharField(_("Subject"), max_length=255, blank=True)
    message = models.TextField(_("Message"))
    
    # Flexible form data
    form_data = models.JSONField(
        _("Form Data"),
        default=dict,
        blank=True,
        help_text=_("Additional form fields as key-value pairs")
    )
    # Example structure:
    # {
    #     "preferred_date": "2024-01-15",
    #     "service_type": "consultation",
    #     "company": "Acme Corp"
    # }
    
    # Source tracking
    source_page = models.ForeignKey(Page, on_delete=models.SET_NULL, null=True, blank=True, related_name='inquiries')
    source_url = models.URLField(_("Source URL"), blank=True)
    ip_address = models.GenericIPAddressField(_("IP Address"), null=True, blank=True)
    user_agent = models.TextField(_("User Agent"), blank=True)
    
    # Processing
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_inquiries'
    )
    notes = models.TextField(_("Internal Notes"), blank=True)
    
    # Notification tracking
    notification_sent = models.BooleanField(_("Notification Sent"), default=False)
    notification_sent_at = models.DateTimeField(_("Notification Sent At"), null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Inquiry")
        verbose_name_plural = _("Inquiries")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['workspace', 'inquiry_type']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_inquiry_type_display()}: {self.subject or self.name}"


class NewsletterSubscription(models.Model):
    """
    Newsletter email subscription per workspace.
    """
    STATUS_CHOICES = (
        ('subscribed', _('Subscribed')),
        ('unsubscribed', _('Unsubscribed')),
    )
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='newsletter_subscriptions')
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='newsletter_subscriptions')
    email = models.EmailField(_("Email"))
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='subscribed')
    source_url = models.URLField(_("Source URL"), blank=True)
    ip_address = models.GenericIPAddressField(_("IP Address"), null=True, blank=True)
    user_agent = models.TextField(_("User Agent"), blank=True)
    unsubscribe_token = models.CharField(_("Unsubscribe Token"), max_length=64, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Newsletter Subscription")
        verbose_name_plural = _("Newsletter Subscriptions")
        ordering = ['-created_at']
        unique_together = (('workspace', 'email'),)
        indexes = [
            models.Index(fields=['workspace', 'status']),
        ]

    def __str__(self):
        return self.email


class NewsletterTemplate(models.Model):
    """
    Reusable template for newsletter content (subject + body).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='newsletter_templates')
    name = models.CharField(_("Name"), max_length=100)
    subject_template = models.CharField(_("Subject Template"), max_length=255)
    body_html = models.TextField(_("Body HTML"), blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Newsletter Template")
        verbose_name_plural = _("Newsletter Templates")
        ordering = ['name']

    def __str__(self):
        return self.name


class NewsletterSend(models.Model):
    """
    A single newsletter send job: content recorded in advance, optional schedule.
    """
    STATUS_CHOICES = (
        ('draft', _('Draft')),
        ('scheduled', _('Scheduled')),
        ('sending', _('Sending')),
        ('sent', _('Sent')),
        ('cancelled', _('Cancelled')),
    )
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='newsletter_sends')
    subject = models.CharField(_("Subject"), max_length=255)
    content = models.TextField(_("Content"), blank=True)
    template = models.ForeignKey(
        NewsletterTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='newsletter_sends'
    )
    scheduled_at = models.DateTimeField(_("Scheduled At"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='draft')
    sent_at = models.DateTimeField(_("Sent At"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='newsletter_sends_created'
    )

    class Meta:
        verbose_name = _("Newsletter Send")
        verbose_name_plural = _("Newsletter Sends")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['scheduled_at']),
        ]

    def __str__(self):
        return self.subject


class NewsletterSendLog(models.Model):
    """
    Per-recipient send result for a NewsletterSend (success/failed, no campaign concept).
    """
    STATUS_CHOICES = (
        ('success', _('Success')),
        ('failed', _('Failed')),
    )
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='newsletter_send_logs')
    newsletter_send = models.ForeignKey(NewsletterSend, on_delete=models.CASCADE, related_name='send_logs')
    subscription = models.ForeignKey(NewsletterSubscription, on_delete=models.CASCADE, related_name='send_logs')
    sent_at = models.DateTimeField(_("Sent At"), default=timezone.now)
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(_("Error Message"), blank=True)

    class Meta:
        verbose_name = _("Newsletter Send Log")
        verbose_name_plural = _("Newsletter Send Logs")
        ordering = ['-sent_at']
        unique_together = (('newsletter_send', 'subscription'),)
        indexes = [
            models.Index(fields=['workspace', 'sent_at']),
            models.Index(fields=['newsletter_send']),
        ]

    def __str__(self):
        return f"{self.newsletter_send_id} -> {self.subscription.email} ({self.status})"

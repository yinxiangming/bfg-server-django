# -*- coding: utf-8 -*-
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
import os

class Workspace(models.Model):
    """
    Workspace model for multi-tenancy support.
    All other models should have a ForeignKey to Workspace.
    """
    # Basic Info
    name = models.CharField(_("Name"), max_length=255)
    slug = models.SlugField(_("Slug"), max_length=100, unique=True)
    
    # Domain
    domain = models.CharField(_("Domain"), max_length=255, blank=True, help_text=_("Primary domain for this workspace"))
    
    # Contact
    email = models.EmailField(_("Email"), blank=True)
    phone = models.CharField(_("Phone"), max_length=50, blank=True)
    
    # Settings
    is_active = models.BooleanField(_("Active"), default=True)
    settings = models.JSONField(_("Settings"), default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Workspace")
        verbose_name_plural = _("Workspaces")
        ordering = ['name']
    
    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Extended user model with additional fields.
    Integrates with django-allauth for authentication.
    """
    # Additional fields beyond AbstractUser
    phone = models.CharField(_("Phone"), max_length=50, blank=True)
    avatar = models.ImageField(_("Avatar"), upload_to='avatars/', blank=True)
    
    # Workspace relationship (user can belong to multiple workspaces via Customer)
    default_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_users',
        verbose_name=_("Default Workspace")
    )
    
    # Preferences
    language = models.CharField(_("Language"), max_length=10, default='en')
    timezone_name = models.CharField(_("Timezone"), max_length=50, default='UTC')
    
    # Timestamps
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
    
    def __str__(self):
        return self.get_full_name() or self.username


class Address(models.Model):
    """
    Generic address model that can be used by any object.
    Uses GenericForeignKey for flexible associations.
    """
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='addresses', verbose_name=_("Workspace"))
    
    # Generic relation to allow address to be linked to any model (Customer, Store, Warehouse, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Contact
    full_name = models.CharField(_("Full Name"), max_length=255)
    phone = models.CharField(_("Phone"), max_length=50)
    email = models.EmailField(_("Email"), blank=True)
    
    # Company (optional)
    company = models.CharField(_("Company"), max_length=255, blank=True)
    
    # Address
    address_line1 = models.CharField(_("Address Line 1"), max_length=255)
    address_line2 = models.CharField(_("Address Line 2"), max_length=255, blank=True)
    city = models.CharField(_("City"), max_length=100)
    state = models.CharField(_("State/Province"), max_length=100, blank=True)
    postal_code = models.CharField(_("Postal Code"), max_length=20)
    country = models.CharField(_("Country"), max_length=2, blank=True)  # ISO 3166-1 alpha-2
    
    # Coordinates
    latitude = models.DecimalField(_("Latitude"), max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(_("Longitude"), max_digits=10, decimal_places=7, null=True, blank=True)
    
    # Notes
    notes = models.TextField(_("Notes"), blank=True)
    
    is_default = models.BooleanField(_("Default"), default=False)
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Address")
        verbose_name_plural = _("Addresses")
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['content_type', 'object_id', 'is_default']),
        ]
    
    def __str__(self):
        return f"{self.full_name} - {self.city}, {self.country}"
    
    def save(self, *args, **kwargs):
        # Ensure only one default address per object per address_type
        if self.is_default and self.content_type and self.object_id:
            Address.objects.filter(
                content_type=self.content_type,
                object_id=self.object_id,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Settings(models.Model):
    """
    Per-workspace configuration settings.
    """
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name='workspace_settings', verbose_name=_("Workspace"))
    
    # General
    site_name = models.CharField(_("Site Name"), max_length=255, blank=True)
    site_description = models.TextField(_("Site Description"), blank=True)
    logo = models.ImageField(_("Logo"), upload_to='settings/logos/', blank=True)
    favicon = models.ImageField(_("Favicon"), upload_to='settings/favicons/', blank=True)
    
    # Localization
    default_language = models.CharField(_("Default Language"), max_length=10, default='en')
    supported_languages = models.JSONField(_("Supported Languages"), default=list)  # ['en', 'zh-hans']
    default_currency = models.CharField(_("Default Currency"), max_length=3, default='NZD')
    default_timezone = models.CharField(_("Default Timezone"), max_length=50, default='UTC')
    
    # Contact
    contact_email = models.EmailField(_("Contact Email"), blank=True)
    support_email = models.EmailField(_("Support Email"), blank=True)
    contact_phone = models.CharField(_("Contact Phone"), max_length=50, blank=True)
    
    # Social
    facebook_url = models.URLField(_("Facebook URL"), blank=True)
    twitter_url = models.URLField(_("Twitter URL"), blank=True)
    instagram_url = models.URLField(_("Instagram URL"), blank=True)
    
    # Features
    features = models.JSONField(_("Enabled Features"), default=dict, blank=True)
    # Example: {"shop": True, "blog": True, "support": True}
    
    # Custom settings
    custom_settings = models.JSONField(_("Custom Settings"), default=dict, blank=True)
    
    # Timestamps
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Settings")
        verbose_name_plural = _("Settings")
    
    def __str__(self):
        return f"Settings for {self.workspace.name}"


class AuditLog(models.Model):
    """
    Audit log for tracking all important actions and changes.
    Records who did what, when, and on which object.
    """
    ACTION_CHOICES = (
        ('create', _('Create')),
        ('update', _('Update')),
        ('delete', _('Delete')),
        ('login', _('Login')),
        ('logout', _('Logout')),
        ('other', _('Other')),
    )
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='audit_logs', verbose_name=_("Workspace"), null=True, blank=True)
    
    # User
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("User")
    )
    
    # Action
    action = models.CharField(_("Action"), max_length=20, choices=ACTION_CHOICES)
    description = models.TextField(_("Description"), blank=True)
    
    # Object reference
    content_type = models.ForeignKey('contenttypes.ContentType', on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(_("Object Representation"), max_length=255, blank=True)
    
    # Changes
    changes = models.JSONField(_("Changes"), default=dict, blank=True)
    
    # Request info
    ip_address = models.GenericIPAddressField(_("IP Address"), null=True, blank=True)
    user_agent = models.TextField(_("User Agent"), blank=True)
    
    # Timestamp
    created_at = models.DateTimeField(_("Created At"), default=timezone.now, db_index=True)
    
    class Meta:
        verbose_name = _("Audit Log")
        verbose_name_plural = _("Audit Logs")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['content_type', 'object_id']),
        ]
    
    def __str__(self):
        return f"{self.action} by {self.user} at {self.created_at}"


def media_upload_to(instance, filename):
    """
    Custom upload_to function for Media files (independent media objects).
    Saves files to: media/{workspace_id}/{folder}/{filename}
    Folder is passed via instance._upload_folder (set in ViewSet before save)
    """
    # Get workspace_id from instance
    workspace_id = instance.workspace_id if hasattr(instance, 'workspace_id') else 1
    
    # Get folder from temporary attribute set in ViewSet
    folder = getattr(instance, '_upload_folder', '').strip('/') if hasattr(instance, '_upload_folder') else ''
    # Ensure folder path is clean (no leading/trailing slashes, no double slashes)
    if folder:
        folder = '/'.join(folder.split('/'))  # Normalize path separators
        folder = folder.strip('/')
    
    # Simplified path: media/{workspace_id}/{folder}/{filename}
    path_parts = ['media', str(workspace_id)]
    if folder:
        path_parts.append(folder)
    path = '/'.join(path_parts)
    return os.path.join(path, filename)


class Media(models.Model):
    """
    Independent media file entity (Image, Video, etc.).
    Can be referenced by multiple modules (ProductMedia, etc.).
    """
    MEDIA_TYPE_CHOICES = (
        ('image', _('Image')),
        ('video', _('Video')),
        ('model_3d', _('3D Model')),
        ('external_video', _('External Video (YouTube/Vimeo)')),
    )
    
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='common_media_files')
    
    # File
    file = models.FileField(_("File"), upload_to=media_upload_to, blank=True, null=True)
    external_url = models.URLField(_("External URL"), blank=True)
    media_type = models.CharField(_("Media Type"), max_length=20, choices=MEDIA_TYPE_CHOICES, default='image')
    
    # Metadata
    alt_text = models.CharField(_("Alt Text"), max_length=255, blank=True)
    
    # Image-specific
    width = models.IntegerField(_("Width"), null=True, blank=True)
    height = models.IntegerField(_("Height"), null=True, blank=True)
    
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='common_media_uploads')
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Media")
        verbose_name_plural = _("Media")
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.media_type} - {self.file.name if self.file else self.external_url}"


class MediaLink(models.Model):
    """
    Generic link between Media and any model (Package, Consignment, Manifest, Product, etc.).
    Uses GenericForeignKey for flexible associations.
    
    This provides a universal way to attach media files to any object type.
    """
    # Reference to the Media object
    media = models.ForeignKey(
        Media,
        on_delete=models.CASCADE,
        related_name='links',
        help_text=_("Reference to the media file object"),
        verbose_name=_("Media")
    )
    
    # Generic relation to allow media to be linked to any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Object-specific metadata
    position = models.PositiveSmallIntegerField(_("Position"), default=100, help_text=_("Display order"))
    description = models.CharField(_("Description"), max_length=255, blank=True, help_text=_("Optional description of the media"))
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Media Link")
        verbose_name_plural = _("Media Links")
        ordering = ['position', 'created_at']
        unique_together = [('content_type', 'object_id', 'media')]  # Prevent duplicate links
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['content_type', 'object_id', 'position']),
        ]
    
    def __str__(self):
        return f"{self.content_object} - {self.media.media_type} {self.position}"
    
    @property
    def file(self):
        """Convenience property to access media file"""
        return self.media.file if self.media else None
    
    @property
    def external_url(self):
        """Convenience property to access media external URL"""
        return self.media.external_url if self.media else None

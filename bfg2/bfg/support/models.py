# -*- coding: utf-8 -*-
"""
Models for BFG Support module.
Ticketing system, knowledge base, and user feedback.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings


class TicketCategory(models.Model):
    """Support ticket category."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='ticket_categories')
    
    name = models.CharField(_("Name"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Ticket Category")
        verbose_name_plural = _("Ticket Categories")
        ordering = ['order', 'name']
    
    def __str__(self):
        return self.name


class TicketPriority(models.Model):
    """Support ticket priority."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='ticket_priorities')
    
    name = models.CharField(_("Name"), max_length=50)
    level = models.PositiveSmallIntegerField(_("Level"))  # 1=Low, 5=Critical
    color = models.CharField(_("Color"), max_length=7, blank=True)  # Hex color
    
    # SLA
    response_time_hours = models.PositiveIntegerField(_("Response Time (hours)"), null=True, blank=True)
    resolution_time_hours = models.PositiveIntegerField(_("Resolution Time (hours)"), null=True, blank=True)
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Ticket Priority")
        verbose_name_plural = _("Ticket Priorities")
        ordering = ['level']
    
    def __str__(self):
        return self.name


class SupportTeam(models.Model):
    """Support team."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='support_teams')
    
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    
    # Members
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='support_teams')
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Support Team")
        verbose_name_plural = _("Support Teams")
        ordering = ['name']
    
    def __str__(self):
        return self.name


class SupportTicket(models.Model):
    """Support ticket."""
    STATUS_CHOICES = (
        ('new', _('New')),
        ('open', _('Open')),
        ('pending', _('Pending Customer')),
        ('on_hold', _('On Hold')),
        ('resolved', _('Resolved')),
        ('closed', _('Closed')),
    )
    
    CHANNEL_CHOICES = (
        ('email', _('Email')),
        ('web', _('Web Form')),
        ('phone', _('Phone')),
        ('chat', _('Live Chat')),
        ('social', _('Social Media')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='support_tickets')
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT, related_name='support_tickets')
    
    # Ticket Info
    ticket_number = models.CharField(_("Ticket Number"), max_length=50, unique=True)
    subject = models.CharField(_("Subject"), max_length=255)
    description = models.TextField(_("Description"))
    
    # Classification
    category = models.ForeignKey(TicketCategory, on_delete=models.SET_NULL, null=True, related_name='tickets')
    priority = models.ForeignKey(TicketPriority, on_delete=models.SET_NULL, null=True, related_name='tickets')
    tags = models.ManyToManyField('TicketTag', blank=True, related_name='tickets')
    
    # Status
    status = models.CharField(_("Status"), max_length=20, choices=STATUS_CHOICES, default='new')
    channel = models.CharField(_("Channel"), max_length=20, choices=CHANNEL_CHOICES, default='web')
    
    # Assignment
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')
    team = models.ForeignKey(SupportTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    
    # Related
    related_order = models.ForeignKey('shop.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    
    # Timestamps
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    first_response_at = models.DateTimeField(_("First Response At"), null=True, blank=True)
    resolved_at = models.DateTimeField(_("Resolved At"), null=True, blank=True)
    closed_at = models.DateTimeField(_("Closed At"), null=True, blank=True)
    
    class Meta:
        verbose_name = _("Support Ticket")
        verbose_name_plural = _("Support Tickets")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['ticket_number']),
            models.Index(fields=['status']),
            models.Index(fields=['assigned_to']),
        ]
    
    def __str__(self):
        return f"{self.ticket_number} - {self.subject}"


class SupportTicketMessage(models.Model):
    """Support ticket message/reply."""
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    
    # Sender
    is_staff_reply = models.BooleanField(_("Staff Reply"), default=False)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='ticket_messages')
    
    message = models.TextField(_("Message"))
    
    # Attachments (simplified)
    attachments = models.JSONField(_("Attachments"), default=list, blank=True)
    
    # Visibility
    is_internal = models.BooleanField(_("Internal Note"), default=False)  # Staff notes not visible to customer
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("Ticket Message")
        verbose_name_plural = _("Ticket Messages")
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.ticket.ticket_number} - Message {self.id}"


class TicketTag(models.Model):
    """Support ticket tag."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='ticket_tags')
    
    name = models.CharField(_("Name"), max_length=50)
    color = models.CharField(_("Color"), max_length=7, blank=True)
    
    class Meta:
        verbose_name = _("Ticket Tag")
        verbose_name_plural = _("Ticket Tags")
        ordering = ['name']
        unique_together = ('workspace', 'name')
    
    def __str__(self):
        return self.name


class TicketAssignment(models.Model):
    """Ticket assignment history."""
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='assignments')
    
    assigned_from = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets_assigned_from')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets_assigned_to')
    
    reason = models.TextField(_("Reason"), blank=True)
    
    assigned_at = models.DateTimeField(_("Assigned At"), default=timezone.now)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='ticket_assignments_made')
    
    class Meta:
        verbose_name = _("Ticket Assignment")
        verbose_name_plural = _("Ticket Assignments")
        ordering = ['-assigned_at']
    
    def __str__(self):
        return f"{self.ticket.ticket_number} → {self.assigned_to}"


class SLA(models.Model):
    """Service Level Agreement."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='slas')
    
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    
    # Targets
    first_response_hours = models.PositiveIntegerField(_("First Response (hours)"))
    resolution_hours = models.PositiveIntegerField(_("Resolution (hours)"))
    
    # Application
    priorities = models.ManyToManyField(TicketPriority, related_name='slas')
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("SLA")
        verbose_name_plural = _("SLAs")
        ordering = ['name']
    
    def __str__(self):
        return self.name


class KnowledgeCategory(models.Model):
    """Knowledge base category."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='knowledge_categories')
    
    name = models.CharField(_("Name"), max_length=100)
    slug = models.SlugField(_("Slug"), max_length=100)
    description = models.TextField(_("Description"), blank=True)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    
    icon = models.CharField(_("Icon"), max_length=50, blank=True)
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Knowledge Category")
        verbose_name_plural = _("Knowledge Categories")
        ordering = ['order', 'name']
        unique_together = ('workspace', 'slug')
    
    def __str__(self):
        return self.name


class KnowledgeBase(models.Model):
    """Knowledge base article."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='knowledge_articles')
    category = models.ForeignKey(KnowledgeCategory, on_delete=models.CASCADE, related_name='articles')
    
    title = models.CharField(_("Title"), max_length=255)
    slug = models.SlugField(_("Slug"), max_length=255)
    content = models.TextField(_("Content"))
    
    # Metadata
    keywords = models.CharField(_("Keywords"), max_length=255, blank=True)
    
    # Stats
    view_count = models.PositiveIntegerField(_("View Count"), default=0)
    helpful_count = models.PositiveIntegerField(_("Helpful Count"), default=0)
    not_helpful_count = models.PositiveIntegerField(_("Not Helpful Count"), default=0)
    
    # Status
    is_published = models.BooleanField(_("Published"), default=False)
    is_featured = models.BooleanField(_("Featured"), default=False)
    
    # Language
    language = models.CharField(_("Language"), max_length=10)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='kb_articles_created')
    
    class Meta:
        verbose_name = _("Knowledge Article")
        verbose_name_plural = _("Knowledge Articles")
        ordering = ['-created_at']
        unique_together = ('workspace', 'slug', 'language')
    
    def __str__(self):
        return self.title


class TicketTemplate(models.Model):
    """Ticket response template."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='ticket_templates')
    
    name = models.CharField(_("Name"), max_length=255)
    subject = models.CharField(_("Subject"), max_length=255, blank=True)
    content = models.TextField(_("Content"))
    
    # Usage
    category = models.ForeignKey(TicketCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='templates')
    
    is_active = models.BooleanField(_("Active"), default=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Ticket Template")
        verbose_name_plural = _("Ticket Templates")
        ordering = ['name']
    
    def __str__(self):
        return self.name


class FeedbackCategory(models.Model):
    """User feedback category."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='feedback_categories')
    
    name = models.CharField(_("Name"), max_length=100)
    icon = models.CharField(_("Icon"), max_length=50, blank=True)
    
    order = models.PositiveSmallIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)
    
    class Meta:
        verbose_name = _("Feedback Category")
        verbose_name_plural = _("Feedback Categories")
        ordering = ['order', 'name']
    
    def __str__(self):
        return self.name


class UserFeedback(models.Model):
    """User feedback on pages or features."""
    FEEDBACK_TYPE_CHOICES = (
        ('bug', _('Bug Report')),
        ('suggestion', _('Suggestion')),
        ('complaint', _('Complaint')),
        ('praise', _('Praise')),
        ('other', _('Other')),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='user_feedback')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='feedback', null=True, blank=True)
    
    # Feedback
    feedback_type = models.CharField(_("Type"), max_length=20, choices=FEEDBACK_TYPE_CHOICES)
    category = models.ForeignKey(FeedbackCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback')
    
    title = models.CharField(_("Title"), max_length=255, blank=True)
    message = models.TextField(_("Message"))
    
    # Context
    page_url = models.URLField(_("Page URL"), max_length=500, blank=True)
    screenshot = models.ImageField(_("Screenshot"), upload_to='feedback/', blank=True)
    
    # Metadata
    browser = models.CharField(_("Browser"), max_length=100, blank=True)
    device = models.CharField(_("Device"), max_length=100, blank=True)
    
    # Status
    is_reviewed = models.BooleanField(_("Reviewed"), default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback_reviewed')
    reviewed_at = models.DateTimeField(_("Reviewed At"), null=True, blank=True)
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    
    class Meta:
        verbose_name = _("User Feedback")
        verbose_name_plural = _("User Feedback")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['feedback_type']),
        ]
    
    def __str__(self):
        return f"{self.get_feedback_type_display()} - {self.title or self.message[:50]}"

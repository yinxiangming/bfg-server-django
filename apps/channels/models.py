# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class ExternalChannel(models.Model):
    CHANNEL_TYPES = [
        ("trademe", "TradeMe"),
        ("shopify", "Shopify"),
        ("ebay", "eBay"),
        ("custom", "Custom"),
    ]

    workspace = models.ForeignKey(
        "common.Workspace",
        on_delete=models.CASCADE,
        related_name="external_channels",
        verbose_name=_("Workspace"),
    )
    channel_type = models.CharField(
        _("Channel Type"),
        max_length=20,
        choices=CHANNEL_TYPES,
    )
    name = models.CharField(_("Name"), max_length=100)
    # TODO: encrypt credentials at rest (e.g. via django-fernet-fields or AWS KMS)
    credentials = models.JSONField(_("Credentials"), default=dict)
    config = models.JSONField(_("Config"), default=dict, blank=True)
    is_active = models.BooleanField(_("Active"), default=True)
    last_sync_at = models.DateTimeField(_("Last Sync At"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("External Channel")
        verbose_name_plural = _("External Channels")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_channel_type_display()})"


class ExternalListing(models.Model):
    STATUS = [
        ("pending", _("Pending")),
        ("active", _("Active")),
        ("ended", _("Ended")),
        ("error", _("Error")),
        ("relisting", _("Relisting")),
    ]

    product = models.ForeignKey(
        "shop.Product",
        on_delete=models.CASCADE,
        related_name="external_listings",
        verbose_name=_("Product"),
    )
    channel = models.ForeignKey(
        ExternalChannel,
        on_delete=models.CASCADE,
        related_name="listings",
        verbose_name=_("Channel"),
    )
    external_id = models.CharField(_("External ID"), max_length=100, blank=True)
    status = models.CharField(
        _("Status"), max_length=20, choices=STATUS, default="pending"
    )
    # Snapshot of the data actually sent to the channel (for diff detection)
    mapped_data = models.JSONField(_("Mapped Data"), default=dict, blank=True)
    # Raw data returned by the channel (URL, views, stats etc.)
    channel_meta = models.JSONField(_("Channel Meta"), default=dict, blank=True)
    expires_at = models.DateTimeField(_("Expires At"), null=True, blank=True)
    last_synced = models.DateTimeField(_("Last Synced"), null=True, blank=True)
    error_detail = models.TextField(_("Error Detail"), blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("External Listing")
        verbose_name_plural = _("External Listings")
        unique_together = ("product", "channel")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product} → {self.channel} [{self.status}]"


class ExternalFeedback(models.Model):
    TYPES = [
        ("positive", _("Positive")),
        ("neutral", _("Neutral")),
        ("negative", _("Negative")),
    ]

    listing = models.ForeignKey(
        ExternalListing,
        on_delete=models.CASCADE,
        related_name="feedback",
        verbose_name=_("Listing"),
    )
    external_id = models.CharField(_("External ID"), max_length=100, unique=True)
    author = models.CharField(_("Author"), max_length=100)
    rating = models.IntegerField(_("Rating"), null=True, blank=True)
    feedback_type = models.CharField(_("Feedback Type"), max_length=20, choices=TYPES)
    comment = models.TextField(_("Comment"), blank=True)
    received_at = models.DateTimeField(_("Received At"))
    reply = models.TextField(_("Reply"), blank=True)
    replied_at = models.DateTimeField(_("Replied At"), null=True, blank=True)
    is_replied = models.BooleanField(_("Is Replied"), default=False)

    class Meta:
        verbose_name = _("External Feedback")
        verbose_name_plural = _("External Feedback")
        ordering = ["-received_at"]

    def __str__(self):
        return f"Feedback {self.external_id} ({self.feedback_type})"


class ExternalQuestion(models.Model):
    ANSWER_STATUS = [
        ("pending", _("Pending")),
        ("answered", _("Answered")),
        ("skipped", _("Skipped")),
    ]

    listing = models.ForeignKey(
        ExternalListing,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name=_("Listing"),
    )
    external_id = models.CharField(_("External ID"), max_length=100, unique=True)
    question_text = models.TextField(_("Question"))
    asker = models.CharField(_("Asker"), max_length=100)
    asked_at = models.DateTimeField(_("Asked At"))
    answer_text = models.TextField(_("Answer"), blank=True)
    answered_at = models.DateTimeField(_("Answered At"), null=True, blank=True)
    answer_status = models.CharField(
        _("Answer Status"), max_length=20, choices=ANSWER_STATUS, default="pending"
    )
    is_auto_answered = models.BooleanField(_("Auto Answered"), default=False)

    class Meta:
        verbose_name = _("External Question")
        verbose_name_plural = _("External Questions")
        ordering = ["-asked_at"]

    def __str__(self):
        return f"Question {self.external_id} [{self.answer_status}]"


class ChannelFAQRule(models.Model):
    channel = models.ForeignKey(
        ExternalChannel,
        on_delete=models.CASCADE,
        related_name="faq_rules",
        verbose_name=_("Channel"),
    )
    # Stored as a JSON list of strings (MySQL does not support ArrayField)
    keywords = models.JSONField(_("Keywords"), default=list)
    answer = models.TextField(_("Answer"))
    priority = models.IntegerField(_("Priority"), default=0)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)

    class Meta:
        verbose_name = _("Channel FAQ Rule")
        verbose_name_plural = _("Channel FAQ Rules")
        ordering = ["-priority"]

    def __str__(self):
        return f"FAQRule({self.channel}, priority={self.priority})"

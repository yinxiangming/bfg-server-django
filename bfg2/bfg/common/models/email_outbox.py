"""Durable workspace mail intents and immutable attachment snapshots."""

import uuid

from django.db import models
from django.utils import timezone

from bfg.common.managers import TenantScopedModel


class EmailOutbox(TenantScopedModel):
    class State(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENDING = 'sending', 'Sending'
        RETRY = 'retry', 'Retry scheduled'
        SENT = 'sent', 'Accepted by transport'

    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    dedupe_key = models.CharField(max_length=200)
    dedupe_hash = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    to_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body_plain = models.TextField()
    body_html = models.TextField(blank=True)
    from_email = models.EmailField(blank=True)
    message_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_token = models.UUIDField(null=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True)
    last_error_code = models.CharField(max_length=40, blank=True)
    sent_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        base_manager_name = 'all_objects'
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'dedupe_hash'], name='email_outbox_intent_unique'),
        ]
        indexes = [
            models.Index(fields=['state', 'next_attempt_at'], name='email_outbox_due'),
            models.Index(fields=['state', 'lease_expires_at'], name='email_outbox_lease'),
            models.Index(fields=['workspace', '-created_at'], name='email_outbox_workspace'),
        ]


class EmailOutboxAttachment(models.Model):
    message = models.ForeignKey(EmailOutbox, on_delete=models.CASCADE, related_name='attachments')
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127)
    content = models.BinaryField()
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        ordering = ['pk']


class EmailOutboxAttempt(models.Model):
    message = models.ForeignKey(EmailOutbox, on_delete=models.CASCADE, related_name='attempts')
    number = models.PositiveIntegerField()
    lease_token = models.UUIDField()
    state = models.CharField(max_length=16, default='sending')
    error_code = models.CharField(max_length=40, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['number']
        constraints = [
            models.UniqueConstraint(fields=['message', 'number'], name='email_outbox_attempt_unique'),
        ]

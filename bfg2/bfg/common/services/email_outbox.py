"""Persist mail before transport, then claim due work with recoverable leases."""

import hashlib
import json
import logging
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from bfg.common.email_backends.attachments import EmailAttachment, validate_attachments
from bfg.common.models import EmailOutbox, EmailOutboxAttachment, EmailOutboxAttempt

logger = logging.getLogger(__name__)
LEASE_SECONDS = 300


def _validate_address(value):
    if not isinstance(value, str) or len(value) > 254 or '\n' in value or '\r' in value:
        raise ValueError('Invalid email address.')
    try:
        validate_email(value)
    except ValidationError:
        raise ValueError('Invalid email address.') from None


def _wake_worker():
    try:
        from bfg.common.tasks import process_email_outbox
        process_email_outbox.delay()
    except Exception:
        # The committed row is recovered by the next scheduled sweep.
        logger.warning('Email outbox worker notification unavailable.')


def enqueue_email(workspace, to_list, subject, body_plain, body_html=None,
                  from_email=None, attachments=None, dedupe_key=None):
    if not isinstance(to_list, (list, tuple)) or len(to_list) != 1:
        raise ValueError('Queued email requires exactly one recipient.')
    _validate_address(to_list[0])
    if from_email is not None and from_email != '':
        _validate_address(from_email)
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 255 or any(
        character in subject for character in ('\r', '\n', '\x00')
    ):
        raise ValueError('Invalid email subject.')
    body_html = '' if body_html is None else body_html
    if not isinstance(body_plain, str) or not isinstance(body_html, str):
        raise ValueError('Invalid email body.')
    if len(body_plain.encode()) + len(body_html.encode()) > 2 * 1024 * 1024:
        raise ValueError('Email body exceeds the size limit.')
    if dedupe_key is None:
        dedupe_key = str(uuid.uuid4())
    if not isinstance(dedupe_key, str) or not dedupe_key.strip() or len(dedupe_key) > 200:
        raise ValueError('Invalid email deduplication key.')
    attachments = validate_attachments(attachments)
    payload = {
        'to_email': to_list[0], 'subject': subject, 'body_plain': body_plain,
        'body_html': body_html, 'from_email': from_email or '',
    }
    fingerprints = [
        {'filename': item.filename, 'content_type': item.content_type,
         'sha256': hashlib.sha256(item.content).hexdigest()}
        for item in attachments
    ]
    fingerprint = hashlib.sha256(json.dumps(
        {**payload, 'attachments': fingerprints}, sort_keys=True, ensure_ascii=True
    ).encode()).hexdigest()
    with transaction.atomic():
        message, created = EmailOutbox.all_objects.get_or_create(
            workspace=workspace, dedupe_hash=hashlib.sha256(dedupe_key.encode()).hexdigest(),
            defaults={**payload, 'dedupe_key': dedupe_key, 'payload_hash': fingerprint},
        )
        if message.payload_hash != fingerprint:
            raise ValueError('Email deduplication key already has a different payload.')
        if created:
            EmailOutboxAttachment.objects.bulk_create([
                EmailOutboxAttachment(
                    message=message, filename=item.filename, content_type=item.content_type,
                    content=item.content, size=len(item.content), sha256=metadata['sha256'],
                )
                for item, metadata in zip(attachments, fingerprints)
            ])
            transaction.on_commit(_wake_worker)
    return message


def _eligible(now):
    return (
        Q(state__in=[EmailOutbox.State.PENDING, EmailOutbox.State.RETRY], next_attempt_at__lte=now)
        | Q(state=EmailOutbox.State.SENDING, lease_expires_at__lte=now)
    )


def _claim(message_id, now):
    token = uuid.uuid4()
    with transaction.atomic():
        updated = EmailOutbox.all_objects.filter(
            pk=message_id, workspace__is_active=True,
        ).filter(_eligible(now)).update(
            state=EmailOutbox.State.SENDING, lease_token=token,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            attempt_count=F('attempt_count') + 1,
        )
        if not updated:
            return None
        message = EmailOutbox.all_objects.select_related('workspace').get(pk=message_id)
        EmailOutboxAttempt.objects.filter(message=message, state='sending').update(
            state='interrupted', error_code='lease_expired', finished_at=now,
        )
        EmailOutboxAttempt.objects.create(
            message=message, number=message.attempt_count, lease_token=token, started_at=now,
        )
    return message


def deliver_claim(message):
    """Send a claimed snapshot and fence completion against a later claim."""
    from bfg.common.services.email_service import EmailService

    if not EmailOutbox.all_objects.filter(
        pk=message.pk, state=EmailOutbox.State.SENDING, lease_token=message.lease_token,
        lease_expires_at__gt=timezone.now(), workspace__is_active=True,
    ).exists():
        return 'superseded'
    error_code = ''
    try:
        config = EmailService.get_active_config(message.workspace)
        if not config:
            error_code = 'email_config_unavailable'
        else:
            attachments = [EmailAttachment(item.filename, bytes(item.content), item.content_type)
                           for item in message.attachments.all()]
            EmailService.send_email(
                message.workspace, [message.to_email], message.subject, message.body_plain,
                body_html=message.body_html or None, from_email=message.from_email or None,
                config=config, attachments=attachments,
                message_id=f'<{message.message_id}@outbox.bfg.invalid>',
            )
    except Exception:
        error_code = 'email_transport_error'

    now = timezone.now()
    state = EmailOutbox.State.RETRY if error_code else EmailOutbox.State.SENT
    delay = min(3600, 60 * 2 ** min(message.attempt_count - 1, 6))
    with transaction.atomic():
        updated = EmailOutbox.all_objects.filter(
            pk=message.pk, state=EmailOutbox.State.SENDING, lease_token=message.lease_token,
        ).update(
            state=state, lease_token=None, lease_expires_at=None, last_error_code=error_code,
            next_attempt_at=now + timedelta(seconds=delay), sent_at=None if error_code else now,
        )
        if updated:
            EmailOutboxAttempt.objects.filter(
                message=message, lease_token=message.lease_token, state='sending',
            ).update(
                state='failed' if error_code else 'accepted', error_code=error_code, finished_at=now,
            )
    return state if updated else 'superseded'


def process_due(limit=100, workspace_id=None):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError('Email batch limit must be between 1 and 1000.')
    # This scheduler intentionally scans tenants without request-local state.
    due = EmailOutbox.all_objects.filter(_eligible(timezone.now()), workspace__is_active=True)
    if workspace_id is not None:
        due = due.filter(workspace_id=workspace_id)
    ids = list(due.order_by('next_attempt_at', 'pk').values_list('pk', flat=True)[:limit])
    result = {'claimed': 0, 'sent': 0, 'retry': 0, 'superseded': 0}
    for message_id in ids:
        message = _claim(message_id, timezone.now())
        if message is not None:
            result['claimed'] += 1
            result[deliver_claim(message)] += 1
    return result


def retry_email(workspace, message_id):
    updated = EmailOutbox.all_objects.filter(
        workspace=workspace, pk=message_id,
        state__in=[EmailOutbox.State.PENDING, EmailOutbox.State.RETRY],
    ).update(next_attempt_at=timezone.now())
    if updated:
        transaction.on_commit(_wake_worker)
    return bool(updated)

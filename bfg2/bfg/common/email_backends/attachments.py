"""Transport-neutral attachment values and payload validation."""

import re
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = 'application/octet-stream'


def validate_attachments(attachments):
    values = tuple(attachments or ())
    if len(values) > 20:
        raise ValueError('Too many email attachments.')
    total = 0
    for attachment in values:
        if not isinstance(attachment, EmailAttachment):
            raise ValueError('Invalid email attachment.')
        if not isinstance(attachment.filename, str) or not attachment.filename.strip():
            raise ValueError('An attachment filename is required.')
        if len(attachment.filename) > 255 or re.search(r'[\x00-\x1f\x7f/\\]', attachment.filename):
            raise ValueError('Invalid attachment filename.')
        if not isinstance(attachment.content, bytes):
            raise ValueError('Attachment content must be bytes.')
        if not isinstance(attachment.content_type, str) or not re.fullmatch(
            r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+', attachment.content_type
        ) or len(attachment.content_type) > 127:
            raise ValueError('Invalid attachment content type.')
        total += len(attachment.content)
    if total > getattr(settings, 'BFG_EMAIL_MAX_ATTACHMENT_BYTES', 10 * 1024 * 1024):
        raise ValueError('Email attachments exceed the size limit.')
    return values

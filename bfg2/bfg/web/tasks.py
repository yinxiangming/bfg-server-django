"""
BFG Web Module

Celery tasks for async operations (email notifications, webhooks)
"""

import logging
import json
import hashlib
import hmac
import requests
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_inquiry_email(self, inquiry_id: int):
    """
    Send email notification for new inquiry
    
    Args:
        inquiry_id: ID of the inquiry
    """
    from bfg.web.models import Inquiry, Site
    
    try:
        inquiry = Inquiry.objects.select_related('site', 'workspace').get(id=inquiry_id)
    except Inquiry.DoesNotExist:
        logger.error(f"Inquiry {inquiry_id} not found")
        return
    
    # Get notification config
    notification_config = {}
    if inquiry.site:
        notification_config = inquiry.site.notification_config or {}
    else:
        default_site = Site.objects.filter(
            workspace=inquiry.workspace,
            is_default=True
        ).first()
        if default_site:
            notification_config = default_site.notification_config or {}
    
    email_config = notification_config.get('email', {})
    if not email_config.get('enabled'):
        return
    
    recipients = email_config.get('recipients', [])
    if not recipients:
        logger.warning(f"No email recipients configured for inquiry {inquiry_id}")
        return
    
    try:
        # Build email content
        subject = f"[{inquiry.get_inquiry_type_display()}] New inquiry from {inquiry.name}"
        
        # Try to render template, fallback to plain text
        try:
            html_message = render_to_string('web/email/inquiry_notification.html', {
                'inquiry': inquiry,
            })
        except Exception:
            html_message = None
        
        text_message = f"""
New {inquiry.get_inquiry_type_display()}

Name: {inquiry.name}
Email: {inquiry.email}
Phone: {inquiry.phone}
Subject: {inquiry.subject}

Message:
{inquiry.message}

---
Submitted at: {inquiry.created_at}
Source: {inquiry.source_url or 'N/A'}
"""
        
        send_mail(
            subject=subject,
            message=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            html_message=html_message,
            fail_silently=False,
        )
        
        # Mark as sent
        inquiry.notification_sent = True
        inquiry.notification_sent_at = timezone.now()
        inquiry.save(update_fields=['notification_sent', 'notification_sent_at'])
        
        logger.info(f"Email notification sent for inquiry {inquiry_id}")
        
    except Exception as exc:
        logger.error(f"Failed to send email for inquiry {inquiry_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_inquiry_webhook(self, inquiry_id: int):
    """
    Send webhook notification for new inquiry
    
    Args:
        inquiry_id: ID of the inquiry
    """
    from bfg.web.models import Inquiry, Site
    
    try:
        inquiry = Inquiry.objects.select_related('site', 'workspace').get(id=inquiry_id)
    except Inquiry.DoesNotExist:
        logger.error(f"Inquiry {inquiry_id} not found")
        return
    
    # Get notification config
    notification_config = {}
    if inquiry.site:
        notification_config = inquiry.site.notification_config or {}
    else:
        default_site = Site.objects.filter(
            workspace=inquiry.workspace,
            is_default=True
        ).first()
        if default_site:
            notification_config = default_site.notification_config or {}
    
    webhook_config = notification_config.get('webhook', {})
    if not webhook_config.get('enabled'):
        return
    
    webhook_url = webhook_config.get('url')
    if not webhook_url:
        logger.warning(f"No webhook URL configured for inquiry {inquiry_id}")
        return
    
    try:
        # Build payload
        payload = {
            'event': 'inquiry.created',
            'timestamp': timezone.now().isoformat(),
            'data': {
                'id': inquiry.id,
                'type': inquiry.inquiry_type,
                'status': inquiry.status,
                'name': inquiry.name,
                'email': inquiry.email,
                'phone': inquiry.phone,
                'subject': inquiry.subject,
                'message': inquiry.message,
                'form_data': inquiry.form_data,
                'source_url': inquiry.source_url,
                'created_at': inquiry.created_at.isoformat(),
            }
        }
        
        # Prepare headers
        headers = {
            'Content-Type': 'application/json',
        }
        
        # Sign payload if secret is configured
        webhook_secret = webhook_config.get('secret')
        if webhook_secret:
            payload_json = json.dumps(payload, separators=(',', ':'))
            signature = hmac.new(
                webhook_secret.encode(),
                payload_json.encode(),
                hashlib.sha256
            ).hexdigest()
            headers['X-Webhook-Signature'] = f"sha256={signature}"
        
        # Send webhook
        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        
        logger.info(f"Webhook sent for inquiry {inquiry_id}, status: {response.status_code}")
        
    except requests.RequestException as exc:
        logger.error(f"Failed to send webhook for inquiry {inquiry_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task
def invalidate_page_cache(page_id: int):
    """
    Invalidate cache for a specific page

    Args:
        page_id: ID of the page to invalidate
    """
    from django.core.cache import cache
    from bfg.web.models import Page

    try:
        page = Page.objects.get(id=page_id)
        cache_key = f"page_rendered:{page.workspace_id}:{page.slug}:{page.language}"
        cache.delete(cache_key)
        logger.info(f"Cache invalidated for page {page_id}")
    except Page.DoesNotExist:
        logger.warning(f"Page {page_id} not found for cache invalidation")


# ---------------------------------------------------------------------------
# Booking notification tasks
# New booking: email + inbox to admin; confirmed: to applicant; confirmed cancelled: to admin
# ---------------------------------------------------------------------------


def _get_staff_emails(workspace_id: int):
    """Return list of email addresses for active staff in the workspace."""
    from bfg.common.models import StaffMember
    staff = StaffMember.objects.filter(
        workspace_id=workspace_id,
        is_active=True
    ).select_related('user')
    emails = []
    for sm in staff:
        if sm.user:
            addr = (getattr(sm.user, 'email', None) or '').strip()
            if addr:
                emails.append(addr)
    return list(set(emails))


def _get_staff_customers(workspace_id: int):
    """Return Customers linked to staff users in this workspace (for inbox)."""
    from bfg.common.models import StaffMember, Customer
    staff_user_ids = StaffMember.objects.filter(
        workspace_id=workspace_id,
        is_active=True
    ).values_list('user_id', flat=True)
    return list(Customer.objects.filter(
        workspace_id=workspace_id,
        user_id__in=staff_user_ids
    ))


def _send_admin_notification(workspace_id: int, subject: str, body: str, action_url: str = ''):
    """Send email to all staff (or workspace email as fallback) and create inbox for staff that have Customer."""
    from bfg.inbox.models import Message, MessageRecipient
    from bfg.common.models import Workspace

    emails = _get_staff_emails(workspace_id)
    if not emails:
        try:
            workspace = Workspace.objects.get(id=workspace_id)
            if getattr(workspace, 'email', None) and (workspace.email or '').strip():
                emails = [workspace.email.strip()]
                logger.info("No staff emails for workspace %s, using workspace email", workspace_id)
        except Workspace.DoesNotExist:
            pass
    if not emails:
        logger.warning(
            "No admin recipients for workspace %s (no staff with email and no workspace.email), skipping",
            workspace_id,
        )
        return

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=emails,
            fail_silently=False,
        )
        logger.info("Booking admin email sent to %s recipients", len(emails))
    except Exception as e:
        logger.exception("Failed to send booking admin email: %s", e)
        raise

    try:
        workspace = Workspace.objects.get(id=workspace_id)
        admin_customers = _get_staff_customers(workspace_id)
        if not admin_customers:
            return
        msg = Message.objects.create(
            workspace=workspace,
            subject=subject,
            message=body,
            message_type='notification',
            sender=None,
            action_url=action_url or '',
            action_label='',
            send_email=False,
            send_sms=False,
            send_push=False,
        )
        for customer in admin_customers:
            MessageRecipient.objects.get_or_create(
                message=msg,
                recipient=customer,
                defaults={'is_read': False},
            )
        logger.info("Booking admin inbox message created for %s recipients", len(admin_customers))
    except Exception as e:
        logger.warning("Failed to create admin inbox message: %s", e)


@shared_task(bind=True, max_retries=3)
def notify_admin_new_booking(self, booking_id: int):
    """Notify admin group (email + inbox) when a new booking is created."""
    from bfg.web.models import Booking
    try:
        booking = Booking.objects.select_related('timeslot', 'customer').get(id=booking_id)
    except Booking.DoesNotExist:
        logger.error("Booking %s not found", booking_id)
        return

    slot = booking.timeslot
    slot_display = f"{slot.date} {slot.start_time}-{slot.end_time}"
    applicant = (
        booking.name or booking.email
        or (getattr(booking.customer, 'user', None) and getattr(booking.customer.user, 'email', None))
        or "Guest"
    )
    subject = f"[Booking] New booking #{booking_id} - {slot_display}"
    body = f"""A new booking has been created.

Booking ID: {booking_id}
Time slot: {slot_display}
Applicant: {applicant}
Contact: {booking.email or booking.phone or 'N/A'}
Status: {booking.status}

Created at: {booking.created_at}
"""
    logger.info("Sending admin new-booking notification for booking %s, workspace %s", booking_id, booking.workspace_id)
    _send_admin_notification(booking.workspace_id, subject, body, "")


@shared_task(bind=True, max_retries=3)
def notify_applicant_confirmed(self, booking_id: int):
    """Send email and inbox to applicant when admin confirms the booking."""
    from bfg.web.models import Booking
    try:
        booking = Booking.objects.select_related('timeslot', 'customer', 'customer__user').get(id=booking_id)
    except Booking.DoesNotExist:
        logger.error("Booking %s not found", booking_id)
        return

    slot = booking.timeslot
    slot_display = f"{slot.date} {slot.start_time}-{slot.end_time}"
    subject = f"Booking confirmed - {slot_display}"
    body = f"""Your booking has been confirmed.

Time slot: {slot_display}
Booking ID: {booking_id}

Thank you.
"""

    # Always send email so applicant receives confirmation even if template is missing
    _send_applicant_email(booking, subject, body)
    # If applicant has a customer account, also send inbox notification
    if booking.customer_id:
        try:
            from bfg.inbox.tasks import send_notification
            send_notification.delay(
                workspace_id=booking.workspace_id,
                customer_id=booking.customer_id,
                template_code='booking_confirmed',
                context_data={'booking_id': booking_id, 'slot_display': slot_display},
            )
            logger.info("Triggered booking_confirmed inbox for customer %s", booking.customer_id)
        except Exception as e:
            logger.warning("Failed to queue booking_confirmed inbox: %s", e)


def _send_applicant_email(booking, subject: str, body: str):
    """Send plain email to applicant. Use booking.email or customer.user.email."""
    to_email = (booking.email or '').strip()
    if not to_email and getattr(booking, 'customer', None) and getattr(booking.customer, 'user', None):
        to_email = (getattr(booking.customer.user, 'email', None) or '').strip()
    if not to_email:
        logger.warning("Booking %s has no email for applicant notification", booking.id)
        return
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[to_email],
            fail_silently=False,
        )
        logger.info("Booking confirmed email sent to applicant %s", to_email)
    except Exception as e:
        logger.exception("Failed to send booking confirmed email: %s", e)
        raise


@shared_task(bind=True, max_retries=3)
def notify_admin_confirmed_cancelled(self, booking_id: int):
    """Notify admin group (email + inbox) when an already-confirmed booking is cancelled."""
    from bfg.web.models import Booking
    try:
        booking = Booking.objects.select_related('timeslot', 'customer', 'customer__user').get(id=booking_id)
    except Booking.DoesNotExist:
        logger.error("Booking %s not found", booking_id)
        return

    slot = booking.timeslot
    slot_display = f"{slot.date} {slot.start_time}-{slot.end_time}"
    applicant = (
        booking.name or booking.email
        or (getattr(booking.customer, 'user', None) and getattr(booking.customer.user, 'email', ''))
        or "Guest"
    )
    subject = f"[Booking] Confirmed booking cancelled #{booking_id} - {slot_display}"
    body = f"""A previously confirmed booking has been cancelled.

Booking ID: {booking_id}
Time slot: {slot_display}
Applicant: {applicant}
Contact: {booking.email or booking.phone or 'N/A'}

Cancelled at: {timezone.now()}
"""
    logger.info("Sending admin cancel notification for booking %s to workspace %s", booking_id, booking.workspace_id)
    _send_admin_notification(booking.workspace_id, subject, body, "")


# ---------------------------------------------------------------------------
# Newsletter: process scheduled sends (call from Celery beat or cron)
# ---------------------------------------------------------------------------


@shared_task
def process_scheduled_newsletter_sends():
    """
    Find NewsletterSend with status=scheduled and scheduled_at <= now, execute send for each.
    Register in Celery beat, e.g. run every minute:
        'process_scheduled_newsletter_sends': {
            'task': 'bfg.web.tasks.process_scheduled_newsletter_sends',
            'schedule': crontab(minute='*'),
        }
    """
    from bfg.web.models import NewsletterSend
    from bfg.web.services import NewsletterService

    now = timezone.now()
    due = NewsletterSend.objects.filter(
        status='scheduled',
        scheduled_at__lte=now,
    ).select_related('workspace')
    for send in due:
        try:
            service = NewsletterService(workspace=send.workspace, user=None)
            service.execute_send(send)
            logger.info("Newsletter send %s executed (scheduled)", send.id)
        except Exception as e:
            logger.exception("Newsletter send %s failed: %s", send.id, e)

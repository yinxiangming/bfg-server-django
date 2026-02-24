"""
Newsletter subscription and send management service.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.html import strip_tags

from bfg.core.services import BaseService
from bfg.web.models import (
    NewsletterSend,
    NewsletterSendLog,
    NewsletterSubscription,
    NewsletterTemplate,
    Site,
)

logger = logging.getLogger(__name__)


class NewsletterService(BaseService):
    """
    Newsletter subscription, send job, and send result recording.
    """

    @transaction.atomic
    def subscribe(
        self,
        email: str,
        site: Optional[Site] = None,
        **kwargs,
    ) -> NewsletterSubscription:
        """Create or re-subscribe; set subscribed and refresh token."""
        sub, created = NewsletterSubscription.objects.update_or_create(
            workspace=self.workspace,
            email=email.strip().lower(),
            defaults={
                "site": site,
                "status": "subscribed",
                "source_url": kwargs.get("source_url", ""),
                "ip_address": kwargs.get("ip_address"),
                "user_agent": kwargs.get("user_agent", ""),
                "unsubscribe_token": kwargs.get("unsubscribe_token") or str(uuid.uuid4()),
                "updated_at": timezone.now(),
            },
        )
        return sub

    @transaction.atomic
    def unsubscribe(
        self,
        email: Optional[str] = None,
        subscription_id: Optional[int] = None,
        token: Optional[str] = None,
    ) -> Optional[NewsletterSubscription]:
        """Set status to unsubscribed by email, id, or token."""
        qs = NewsletterSubscription.objects.filter(workspace=self.workspace)
        if subscription_id:
            qs = qs.filter(id=subscription_id)
        elif email:
            qs = qs.filter(email=email.strip().lower())
        elif token:
            qs = qs.filter(unsubscribe_token=token)
        else:
            return None
        sub = qs.first()
        if sub:
            sub.status = "unsubscribed"
            sub.save(update_fields=["status", "updated_at"])
        return sub

    def get_subscriptions(
        self,
        status: Optional[str] = None,
    ) -> QuerySet[NewsletterSubscription]:
        """List subscriptions for workspace, optional status filter."""
        qs = NewsletterSubscription.objects.filter(workspace=self.workspace).order_by("-created_at")
        if status:
            qs = qs.filter(status=status)
        return qs

    @transaction.atomic
    def record_send_result(
        self,
        newsletter_send: NewsletterSend,
        subscription: NewsletterSubscription,
        status: str = "success",
        error_message: str = "",
    ) -> NewsletterSendLog:
        """Create one send log; if (send, subscription) exists, raise."""
        if not self.can_send_to(subscription, newsletter_send):
            existing = NewsletterSendLog.objects.get(
                newsletter_send=newsletter_send,
                subscription=subscription,
            )
            return existing
        return NewsletterSendLog.objects.create(
            workspace=self.workspace,
            newsletter_send=newsletter_send,
            subscription=subscription,
            status=status,
            error_message=error_message or "",
        )

    def get_send_logs(
        self,
        newsletter_send_id: Optional[int] = None,
        subscription_id: Optional[int] = None,
    ) -> QuerySet[NewsletterSendLog]:
        """List send logs, optional filters."""
        qs = NewsletterSendLog.objects.filter(workspace=self.workspace).select_related(
            "newsletter_send", "subscription"
        ).order_by("-sent_at")
        if newsletter_send_id:
            qs = qs.filter(newsletter_send_id=newsletter_send_id)
        if subscription_id:
            qs = qs.filter(subscription_id=subscription_id)
        return qs

    def can_send_to(self, subscription: NewsletterSubscription, newsletter_send: NewsletterSend) -> bool:
        """True if this subscription has no SendLog for this send (and is subscribed)."""
        if subscription.status != "subscribed":
            return False
        return not NewsletterSendLog.objects.filter(
            newsletter_send=newsletter_send,
            subscription=subscription,
        ).exists()

    @transaction.atomic
    def create_send(
        self,
        subject: str,
        content: str = "",
        template: Optional[NewsletterTemplate] = None,
        scheduled_at: Optional[datetime] = None,
        created_by=None,
    ) -> NewsletterSend:
        """Create a draft or scheduled send."""
        status = "scheduled" if scheduled_at else "draft"
        return NewsletterSend.objects.create(
            workspace=self.workspace,
            subject=subject,
            content=content or "",
            template=template,
            scheduled_at=scheduled_at,
            status=status,
            created_by=created_by,
        )

    @transaction.atomic
    def schedule_send(self, newsletter_send: NewsletterSend, scheduled_at: datetime) -> NewsletterSend:
        """Set scheduled_at and status=scheduled."""
        self.validate_workspace_access(newsletter_send)
        newsletter_send.scheduled_at = scheduled_at
        newsletter_send.status = "scheduled"
        newsletter_send.save(update_fields=["scheduled_at", "status", "updated_at"])
        return newsletter_send

    def _send_one_newsletter_email(
        self,
        newsletter_send: NewsletterSend,
        to_email: str,
    ) -> tuple[bool, str]:
        """
        Send one newsletter email. Uses send.subject and send.content (no template required).
        Plain text when content has no HTML; otherwise HTML with plain fallback.
        Returns (success, error_message).
        """
        subject = (newsletter_send.subject or "").strip() or "(No subject)"
        body = (newsletter_send.content or "").strip() or "(No content)"
        try:
            from bfg.common.services import EmailService
            if "<" in body and ">" in body:
                plain_fallback = strip_tags(body) or body[:2000]
                EmailService.send_email(
                    self.workspace,
                    to_list=[to_email],
                    subject=subject,
                    body_plain=plain_fallback,
                    body_html=body,
                )
            else:
                EmailService.send_email(
                    self.workspace,
                    to_list=[to_email],
                    subject=subject,
                    body_plain=body,
                )
            return True, ""
        except ValueError as e:
            logger.warning("Newsletter skip (no workspace email config): %s", e)
            return False, str(e)
        except Exception as e:
            logger.exception("Newsletter send failed to %s: %s", to_email, e)
            return False, str(e)

    @transaction.atomic
    def execute_send(self, newsletter_send: NewsletterSend) -> NewsletterSend:
        """
        For each subscribed subscription without a SendLog, send email (subject + content,
        no template required) and record result. Plain text when content has no HTML.
        """
        self.validate_workspace_access(newsletter_send)
        if newsletter_send.status not in ("draft", "scheduled"):
            return newsletter_send
        newsletter_send.status = "sending"
        newsletter_send.save(update_fields=["status", "updated_at"])
        try:
            subs = self.get_subscriptions(status="subscribed")
            for sub in subs:
                if not self.can_send_to(sub, newsletter_send):
                    continue
                success, err_msg = self._send_one_newsletter_email(newsletter_send, sub.email)
                self.record_send_result(
                    newsletter_send,
                    sub,
                    status="success" if success else "failed",
                    error_message=err_msg,
                )
            newsletter_send.status = "sent"
            newsletter_send.sent_at = timezone.now()
            newsletter_send.save(update_fields=["status", "sent_at", "updated_at"])
        except Exception:
            newsletter_send.status = "draft"
            newsletter_send.save(update_fields=["status", "updated_at"])
            raise
        return newsletter_send

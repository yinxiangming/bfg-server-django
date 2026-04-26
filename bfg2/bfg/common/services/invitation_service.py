# -*- coding: utf-8 -*-
"""
Invitation Service

Creates Invitations, sends emails, validates tokens, and accepts them
(creating the StaffMember row).
"""

import logging
from datetime import timedelta
from typing import Iterable, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.urls import NoReverseMatch
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from bfg.common.models import (
    Invitation,
    StaffMember,
    StaffRole,
    Workspace,
    generate_invitation_token,
    hash_invitation_token,
)
from bfg.common.services.email_service import EmailService

logger = logging.getLogger(__name__)


DEFAULT_EXPIRY_HOURS = 48
MAX_EXPIRY_HOURS = 24 * 14  # hard cap: 14 days


def _build_accept_url(invitation: Invitation, raw_token: str) -> str:
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if not base:
        base = "http://localhost:3000"
    return f"{base}/auth/invite/accept?token={raw_token}&uuid={invitation.uuid}"


def _expiry_hours(requested: Optional[int]) -> int:
    """Resolve the invitation TTL, clamped to a sane range."""
    default = int(getattr(settings, "INVITATION_EXPIRY_HOURS", DEFAULT_EXPIRY_HOURS))
    hours = requested if requested is not None else default
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = default
    if hours < 1:
        hours = 1
    if hours > MAX_EXPIRY_HOURS:
        hours = MAX_EXPIRY_HOURS
    return hours


def _render_email(invitation: Invitation, accept_url: str) -> Tuple[str, str, str]:
    workspace_name = invitation.workspace.name
    role_name = invitation.role.name
    inviter = (
        invitation.invited_by.get_full_name() or invitation.invited_by.email
        if invitation.invited_by
        else workspace_name
    )
    subject = f"You're invited to join {workspace_name}"
    expiry_local = timezone.localtime(invitation.expires_at).strftime("%Y-%m-%d %H:%M")
    intro = (
        f"{inviter} has invited you to join {workspace_name} as {role_name}."
    )
    welcome = invitation.message.strip() if invitation.message else ""

    body_parts = [intro]
    if welcome:
        body_parts.append("")
        body_parts.append(welcome)
    body_parts.extend(
        [
            "",
            f"Click the link below before {expiry_local} to accept:",
            accept_url,
            "",
            "If you didn't expect this invitation, you can ignore this email.",
        ]
    )
    body_plain = "\n".join(body_parts)

    welcome_html = (
        f'<blockquote style="border-left:3px solid #ddd;padding:0 12px;color:#555;">'
        f"{welcome}</blockquote>"
        if welcome
        else ""
    )
    body_html = f"""
        <p>{intro}</p>
        {welcome_html}
        <p><a href="{accept_url}"
              style="display:inline-block;padding:10px 16px;background:#2563eb;
                     color:#fff;border-radius:6px;text-decoration:none;">
            Accept invitation
        </a></p>
        <p style="color:#888;font-size:12px;">
            This link expires on {expiry_local}.
            If the button doesn't work, copy this URL into your browser:<br>
            <span style="word-break:break-all;">{accept_url}</span>
        </p>
    """
    return subject, body_plain, body_html


class InvitationService:
    """Workspace-scoped invitation operations."""

    def __init__(self, workspace: Workspace, actor=None):
        self.workspace = workspace
        self.actor = actor

    # ── Creation ──────────────────────────────────────────────────────

    @transaction.atomic
    def create(
        self,
        *,
        email: str,
        role: StaffRole,
        expiry_hours: Optional[int] = None,
        message: str = "",
        send_email: bool = True,
    ) -> Tuple[Invitation, str]:
        email = email.strip().lower()
        if not email:
            raise ValidationError({"email": "Email is required."})
        if role.workspace_id != self.workspace.id:
            raise ValidationError({"role": "Role does not belong to this workspace."})

        # Block if user is already an active staff member.
        if StaffMember.objects.filter(
            workspace=self.workspace,
            user__email__iexact=email,
            is_active=True,
        ).exists():
            raise ValidationError(
                {"email": "This user is already a staff member of this workspace."}
            )

        # Block if there's an existing pending (and not-yet-expired) invitation.
        existing = (
            Invitation.objects.select_for_update()
            .filter(
                workspace=self.workspace,
                email__iexact=email,
                status=Invitation.STATUS_PENDING,
            )
            .first()
        )
        if existing:
            if existing.is_expired:
                existing.mark_expired()
            else:
                raise ValidationError(
                    {"email": "There is already a pending invitation for this email."}
                )

        raw_token = generate_invitation_token()
        invitation = Invitation.objects.create(
            workspace=self.workspace,
            email=email,
            role=role,
            invited_by=self.actor if getattr(self.actor, "is_authenticated", False) else None,
            token_hash=hash_invitation_token(raw_token),
            expires_at=timezone.now() + timedelta(hours=_expiry_hours(expiry_hours)),
            message=message or "",
        )

        if send_email:
            try:
                self._send_email(invitation, raw_token)
            except Exception:  # noqa: BLE001 — surface as warning, don't fail the create
                logger.exception("Failed to send invitation email to %s", email)

        return invitation, raw_token

    # ── Resend / Revoke ───────────────────────────────────────────────

    @transaction.atomic
    def resend(
        self, invitation: Invitation, *, expiry_hours: Optional[int] = None
    ) -> Tuple[Invitation, str]:
        if invitation.workspace_id != self.workspace.id:
            raise PermissionDenied()
        if invitation.status not in (
            Invitation.STATUS_PENDING,
            Invitation.STATUS_EXPIRED,
        ):
            raise ValidationError(
                {"detail": f"Cannot resend an invitation in status '{invitation.status}'."}
            )

        raw_token = generate_invitation_token()
        invitation.token_hash = hash_invitation_token(raw_token)
        invitation.status = Invitation.STATUS_PENDING
        invitation.expires_at = timezone.now() + timedelta(
            hours=_expiry_hours(expiry_hours)
        )
        invitation.save(
            update_fields=["token_hash", "status", "expires_at", "updated_at"]
        )

        try:
            self._send_email(invitation, raw_token)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to resend invitation email to %s", invitation.email)
        return invitation, raw_token

    def revoke(self, invitation: Invitation) -> Invitation:
        if invitation.workspace_id != self.workspace.id:
            raise PermissionDenied()
        if invitation.status == Invitation.STATUS_ACCEPTED:
            raise ValidationError({"detail": "Cannot revoke an accepted invitation."})
        invitation.mark_revoked()
        return invitation

    # ── Email ─────────────────────────────────────────────────────────

    def _send_email(self, invitation: Invitation, raw_token: str) -> None:
        accept_url = _build_accept_url(invitation, raw_token)
        subject, body_plain, body_html = _render_email(invitation, accept_url)
        try:
            EmailService.send_email(
                workspace=self.workspace,
                to_list=[invitation.email],
                subject=subject,
                body_plain=body_plain,
                body_html=body_html,
            )
        except ValueError as exc:
            # No active EmailConfig — fall back to Django's default mailer if configured.
            from django.core.mail import send_mail

            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
            if not from_email:
                raise exc
            send_mail(
                subject=subject,
                message=body_plain,
                from_email=from_email,
                recipient_list=[invitation.email],
                html_message=body_html,
            )


# ── Token resolution + acceptance (no workspace context required) ─────


def find_invitation_by_token(raw_token: str, uuid_str: Optional[str] = None) -> Invitation:
    if not raw_token:
        raise ValidationError({"token": "Token is required."})
    qs = Invitation.objects.select_related("workspace", "role")
    invitation = qs.filter(token_hash=hash_invitation_token(raw_token)).first()
    if not invitation:
        raise ValidationError({"token": "Invalid invitation token."})
    if uuid_str and str(invitation.uuid) != str(uuid_str):
        raise ValidationError({"token": "Invitation token mismatch."})
    if invitation.status == Invitation.STATUS_PENDING and invitation.is_expired:
        invitation.mark_expired()
    return invitation


@transaction.atomic
def accept_invitation(invitation: Invitation, user) -> StaffMember:
    """Accept an invitation, creating or reactivating the StaffMember row."""
    if invitation.status == Invitation.STATUS_ACCEPTED:
        raise ValidationError({"detail": "Invitation already accepted."})
    if invitation.status == Invitation.STATUS_REVOKED:
        raise ValidationError({"detail": "Invitation was revoked."})
    if invitation.status == Invitation.STATUS_EXPIRED or invitation.is_expired:
        if invitation.status != Invitation.STATUS_EXPIRED:
            invitation.mark_expired()
        raise ValidationError({"detail": "Invitation has expired."})
    if (user.email or "").lower() != invitation.email.lower():
        raise ValidationError(
            {
                "detail": (
                    "Please sign in or sign up with the email address the invitation "
                    f"was sent to ({invitation.email})."
                )
            }
        )
    if not invitation.workspace.is_active:
        raise ValidationError({"detail": "Workspace is not active."})

    member, created = StaffMember.all_objects.get_or_create(
        workspace=invitation.workspace,
        user=user,
        defaults={"role": invitation.role, "is_active": True},
    )
    if not created:
        member.role = invitation.role
        member.is_active = True
        member.save(update_fields=["role", "is_active", "updated_at"])

    invitation.mark_accepted(user)
    return member
